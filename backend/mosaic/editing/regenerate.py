"""Regenerating one beat (PRODUCT.md §8; S16; ADR 0069): a fresh take on a beat's free
shots while the owner's locked shots keep their cut and their slot.

The selector (``reselect`` prompt) chooses only the free slots, from the beat's pool,
never a clip the edit uses elsewhere or the owner took out. Its picks fill the free slots
in order around the locked ones, so a locked shot keeps its place in the beat. The new
storyboard is timed like any edit (``resolve``) and saved as an ``ai`` version. The
selector decides clips, never timing (invariant 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, cast

from mosaic.ai.client import AIClient
from mosaic.ai.prompts.reselect.schema_v1 import Output as ReselectOut
from mosaic.ai.registry import task_check_ready, task_choice
from mosaic.core.keys import artifact_key
from mosaic.core.time import parse_rational
from mosaic.editing import draft
from mosaic.editing.draft import Board, BoardBeat, BoardShot, DraftError
from mosaic.editing.request import EditRequest
from mosaic.editing.retrieval import Candidate
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.context import TripContext
from mosaic.storage.config import NotConfiguredError

RESELECT = ("reselect", 1)
RESELECT_MAX_TOKENS = 8000
BEAT_VERSION = "beat/1"


@dataclass(frozen=True)
class Slots:
    """A beat's slots: the fixed ones (locked, or absorbed into a locked cut) by index,
    how many are free, and how many picks keep every fixed shot at its index."""

    beat: BoardBeat
    fixed: dict[int, BoardShot]
    free: int
    needed: int


def slots(board: Board, beat_id: str) -> Slots:
    _, beat = board.beat(beat_id)
    fixed = {i: sh for i, sh in enumerate(beat.shots) if sh.locked or sh.absorbed_by}
    free = len(beat.shots) - len(fixed)
    if not beat.shots:
        free = 1  # an empty beat: at least one new shot
    if free == 0:
        raise DraftError("every shot in this beat is locked: unlock one to regenerate it")
    last = max(fixed, default=-1)
    needed = sum(1 for i in range(last) if i not in fixed)
    return Slots(beat, fixed, free, max(1, needed))


def avoid(board: Board, beat_id: str) -> set[str]:
    """Clips the new take may not use: the other beats' and what the owner took out."""
    return {sh.segment_id for b in board.beats if b.beat_id != beat_id for sh in b.shots} | set(
        board.excluded
    )


def context(
    req: EditRequest,
    board: Board,
    sl: Slots,
    by_ref: dict[str, Candidate],
    pace_pref_s: Fraction,
    trip: TripContext,
) -> dict[str, Any]:
    from mosaic.editing.generate import request_summary

    beat = sl.beat
    banned = avoid(board, beat.beat_id) | {sh.segment_id for sh in sl.fixed.values()}
    pool = [r for r in dict.fromkeys(beat.pool) if r in by_ref and r not in banned]
    total = sum(b.share_percent for b in board.beats) or 1
    seconds = Fraction(req.duration_s * beat.share_percent, total)
    lines = []
    for i, sh in enumerate(beat.shots):
        if i in sl.fixed:
            c = by_ref.get(sh.segment_id)
            what = c.line() if c else sh.segment_id
            lines.append(f"{i + 1}. locked: {what}")
        else:
            lines.append(f"{i + 1}. free")
    if not beat.shots:
        lines.append("1. free")
    return {
        "trip_context": trip.prompt_text(),
        "request": request_summary(req),
        "instructions": req.instructions or "(none)",
        "pace": f"{req.pace} (preferred shot about {float(pace_pref_s):.1f} s)",
        "beat": (
            f"{beat.beat_id}: {beat.title}. Intent: {beat.intent}. Target: about {round(seconds)} s"
        ),
        "slots": "\n".join(lines),
        "free_slots": sl.free,
        "avoid": ", ".join(sorted(banned)) or "(none)",
        "pool": "\n".join(by_ref[r].detail() for r in pool) or "(no clips)",
        # For validation and the offline fake adapter.
        "beat_id": beat.beat_id,
        "pool_refs": pool,
        "current_refs": [sh.segment_id for sh in beat.shots],
        "free_slot_count": sl.free,
        "speech_refs": [r for r in pool if by_ref[r].has_speech],
        "candidate_assets": {r: by_ref[r].asset_id for r in pool},
    }


def pool_problem(pool: list[str], sl: Slots, title: str) -> str | None:
    """Why no answer could fill the beat (checked before any AI call), or None."""
    if not pool:
        return f"no clips left for {title}: every one is used or taken out"
    if len(pool) < sl.needed:
        return (
            f"{title} has {len(pool)} clips left for {sl.needed} free slots before its "
            "locked shots: unlock or move a shot, or add clips"
        )
    return None


def check(answer: ReselectOut, beat_id: str, pool: set[str], needed: int) -> list[str]:
    """Problems with a reselect answer (fed back to the model on retry; invariant 6)."""
    errors = []
    if answer.beat_id != beat_id:
        errors.append(f"beat_id must be {beat_id}")
    seen: set[str] = set()
    for x in answer.selections:
        if x.segment_id not in pool:
            errors.append(f"{x.segment_id} is not in the pool")
        if x.segment_id in seen:
            errors.append(f"{x.segment_id} is chosen twice")
        seen.add(x.segment_id)
        errors += [
            f"alternative {a.segment_id} is not in the pool"
            for a in x.alternatives
            if a.segment_id not in pool
        ]
    if len(answer.selections) < needed:
        errors.append(f"choose at least {needed} shots: one for every free slot")
    return errors


def merge(
    board: Board,
    sl: Slots,
    answer: ReselectOut,
    by_ref: dict[str, Candidate],
    known_refs: set[str] | frozenset[str] = frozenset(),
) -> Board:
    """The storyboard with the beat's free slots refilled in order around its fixed
    shots, which keep their index. New picks get new refs in the beat's numbering, past
    every ref the edit has had (``known_refs``), so no ref ever names two clips."""
    out = board.model_copy(deep=True)
    _, beat = out.beat(sl.beat.beat_id)
    prefix = f"{beat.beat_id}#"
    refs = {sh.ref for b in out.beats for sh in b.shots} | set(known_refs)
    used = [
        int(r[len(prefix) :]) for r in refs if r.startswith(prefix) and r[len(prefix) :].isdigit()
    ]
    nxt = max(used, default=-1) + 1
    fresh = []
    for x in answer.selections:
        cand = by_ref[x.segment_id]
        fresh.append(
            BoardShot(
                ref=f"{prefix}{nxt}",
                segment_id=x.segment_id,
                role=x.role,
                priority=x.priority,
                length=x.length,
                audio_intent=(
                    "natural_sound"
                    if x.audio_intent == "dialogue" and not cand.has_speech
                    else x.audio_intent
                ),
                reason=x.reason,
                alternatives=[a.model_dump() for a in x.alternatives],
            )
        )
        nxt += 1
    picks = iter(fresh)
    shots: list[BoardShot] = []
    for i in range(len(beat.shots)):
        if i in sl.fixed:
            shots.append(sl.fixed[i])
        else:
            pick = next(picks, None)
            if pick is not None:
                shots.append(pick)
    shots.extend(picks)
    beat.shots = shots
    return out


def known_refs(s: Any, edit_id: int) -> set[str]:
    """Every pick ref the edit's versions have used."""
    from sqlalchemy import select

    from mosaic.storage.models_project import EditVersion

    out: set[str] = set()
    q = select(EditVersion.timeline, EditVersion.beats).where(EditVersion.edit_id == edit_id)
    for timeline, beats in s.execute(q.execution_options(yield_per=20)):  # invariant 13
        out |= set(timeline.get("selections", {}))
        out |= {sh["ref"] for b in beats for sh in b.get("shots", [])}
    return out


def take_number(s: Any, edit_id: int, beat_id: str) -> int:
    """How many times this beat has been regenerated, plus one: the AI call's variant,
    so each regeneration is a fresh take, and a retry of the same one replays the cache."""
    from sqlalchemy import select

    from mosaic.storage.models_project import EditVersion

    return 1 + sum(
        1
        for (metrics,) in s.execute(
            select(EditVersion.metrics)
            .where(EditVersion.edit_id == edit_id)
            .execution_options(yield_per=50)
        )
        if (metrics.get("regenerated") or {}).get("beat_id") == beat_id
    )


ATTEMPTS = 3  # a draft that changes while the AI answers: saved, and the take redone


@task("edit.regenerate_beat", checkpoint=True)
def regenerate_beat_task(ctx: TaskContext) -> dict[str, Any]:
    edit_id = int(ctx.params["edit_id"])
    beat_id = str(ctx.params["beat_id"])
    try:
        task_check_ready(ctx, "selector")
    except NotConfiguredError as exc:
        raise PermanentError(str(exc)) from None
    for _ in range(ATTEMPTS):
        ctx.check_cancelled()
        try:
            return _attempt(ctx, edit_id, beat_id)
        except draft.DraftChangedError:
            continue  # the owner changed the storyboard meanwhile: keep it, and redo
    raise PermanentError("the storyboard kept changing while this beat was regenerated")


def _attempt(ctx: TaskContext, edit_id: int, beat_id: str) -> dict[str, Any]:
    from mosaic.editing.generate import (
        EDIT_VERSION,
        edit_inputs,
        export_path,
        version_json,
        write_export,
    )
    from mosaic.editing.resolve import rejected_segments
    from mosaic.editing.service import save_draft
    from mosaic.storage.models_project import Edit

    # Changes made since the job was queued are kept, as a version of their own.
    save_draft(ctx.project, edit_id, creator="system", reason="Saved before regenerate")
    with ctx.project.db.session() as s:
        d = draft.load(s, edit_id)
        req = EditRequest.model_validate(d.base.request)
        inp = edit_inputs(s, req)
        try:
            sl = slots(d.board, beat_id)
        except DraftError as exc:
            raise PermanentError(str(exc)) from None
        by_ref = {c.ref: c for c in inp.cands}
        pref_s = Fraction(inp.pace.preferred) / parse_rational(inp.rate)
        pctx = context(req, d.board, sl, by_ref, pref_s, inp.trip)
        refs = known_refs(s, edit_id)
        take = take_number(s, edit_id, beat_id)
        rejected = sorted(rejected_segments(s))
    problem = pool_problem(pctx["pool_refs"], sl, sl.beat.title)
    if problem:
        raise PermanentError(problem)
    ctx.set_stage(f"choosing shots for {sl.beat.title}")
    choice = task_choice(ctx, "selector")
    res = AIClient(ctx).structured(
        "selector",
        *RESELECT,
        pctx,
        max_tokens=RESELECT_MAX_TOKENS,
        # The take, within the edit's own variant: each take of each variant is fresh.
        variant=take * 1000 + req.variant,
        validate=lambda a: check(a, beat_id, set(pctx["pool_refs"]), sl.needed),
    )
    answer = cast(ReselectOut, res.data)
    board = merge(d.board, sl, answer, by_ref, refs)
    ctx.set_stage("timing")
    with ctx.project.db.session() as s:
        done = draft.timed(s, req, inp, board)
    key = artifact_key(
        "edit.beat",
        project_id=ctx.project.id,
        inputs={
            "base": d.base.key,
            "beat": beat_id,
            "take": take,
            "candidates": inp.digest,
            "rejected": rejected,
        },
        config={"selector": [choice.provider, choice.model], "prompt": list(RESELECT)},
        version=f"{BEAT_VERSION}+{EDIT_VERSION}",
    )
    t = draft.Timed(draft.Draft(d.base, board, [], False, False), done, key)
    with ctx.write() as s:
        row = draft.commit(
            s,
            edit_id,
            t,
            creator="ai",
            reason=f"Regenerated “{sl.beat.title}”",
            extra_metrics={
                "regenerated": {"beat_id": beat_id, "take": take, "locked_kept": len(sl.fixed)},
                "ai": {
                    "selector": {
                        "provider": res.provider,
                        "model": res.model,
                        "cached": res.cached,
                    },
                    "cost_usd": round(res.cost_usd, 6),
                },
            },
            input_keys=[f"prov:{res.provenance_id}"],
        )
        edit = s.get(Edit, edit_id)
        if edit is None:
            raise PermanentError(f"edit {edit_id} not found")
        number, payload = row.version, version_json(edit, row)
    path = export_path(ctx.project.workspace, edit_id, number)
    write_export(path, payload)
    return {"edit_id": edit_id, "version": number, "beat_id": beat_id, "export": str(path)}
