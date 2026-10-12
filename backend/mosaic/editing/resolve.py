"""The deterministic half of an edit (ARCHITECTURE.md §9): a plan and its selection in,
the timed timeline out, with no AI call. Solver → refiner → critic, so positions come
only from here (invariant 5). ``edit.generate`` calls it after the planner and selector;
drafts, locks and regeneration call it on their own (M4)."""

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
from mosaic.ai.prompts.selector.schema_v2 import Output as SelectOut
from mosaic.editing import critic, refiner, solver
from mosaic.editing.request import EditRequest, PaceFrames, target_frames
from mosaic.editing.retrieval import Candidate
from mosaic.library import decisions
from mosaic.library.context import TripContext
from mosaic.storage.models_project import (
    ClipDecision,
    Disposition,
    Segment,
    TechMetric,
    TranscriptSegment,
    TranscriptWord,
)


@dataclass(frozen=True)
class EditInputs:
    """What an edit is planned from, before any AI call: the timeline rate, pace, the
    retrieved candidates and a digest of everything they were derived from."""

    rate: str
    pace: PaceFrames
    cands: list[Candidate]
    counts: dict[str, int]
    digest: str
    trip: TripContext


def rejected_segments(s: Session) -> set[int]:
    """The owner's rejections (segment or clip), plus the analysis's where the owner
    decided nothing (invariant 10; ADR 0042)."""
    ai_rejected = {
        sid
        for sid in s.scalars(
            select(Disposition.segment_id).where(
                Disposition.status == "REJECT",
                Disposition.source == "ai",
                Disposition.segment_id.is_not(None),
            )
        )
        if sid is not None
    }
    overridden = set(s.scalars(select(Disposition.segment_id).where(Disposition.source == "user")))
    overridden |= _clip_kept(s)
    return decisions.user_rejected(s) | (ai_rejected - overridden)


def clip_context(session: Session, c: Candidate) -> refiner.ClipContext:
    a, b = c.start, c.end
    words = [
        (s, e)
        for s, e in session.execute(
            select(TranscriptWord.start_ticks, TranscriptWord.end_ticks)
            .where(
                TranscriptWord.asset_id == c.asset_id,
                TranscriptWord.start_ticks < b,
                TranscriptWord.end_ticks > a,
            )
            .order_by(TranscriptWord.start_ticks)
        )
    ]
    sentences = [
        (s, e)
        for s, e in session.execute(
            select(TranscriptSegment.start_ticks, TranscriptSegment.end_ticks)
            .where(
                TranscriptSegment.asset_id == c.asset_id,
                TranscriptSegment.start_ticks < b,
                TranscriptSegment.end_ticks > a,
            )
            .order_by(TranscriptSegment.start_ticks)
        )
    ]
    motion = [
        (s, e, v)
        for s, e, v in session.execute(
            select(TechMetric.start_ticks, TechMetric.end_ticks, TechMetric.value)
            .where(
                TechMetric.asset_id == c.asset_id,
                TechMetric.name == "motion",
                TechMetric.start_ticks < b,
                TechMetric.end_ticks > a,
            )
            .order_by(TechMetric.start_ticks)
        )
    ]
    best_time = (c.obs.get("best_frame") or {}).get("time") or {}
    best = best_time.get("ticks") if best_time.get("tb") == c.tb else None
    return refiner.ClipContext(words, sentences, motion, best)


def _clip_kept(s: Session) -> set[int]:
    """Segments of clips the owner keeps (clip USE or MAYBE, or always include): their AI
    REJECT no longer counts."""
    keeping = select(ClipDecision.asset_id).where(
        (ClipDecision.include == "always")
        | (ClipDecision.disposition.in_(("USE", "MAYBE")) & ClipDecision.include.is_(None))
    )
    return set(s.scalars(select(Segment.id).where(Segment.asset_id.in_(keeping))))


def shots_from_selection(
    plan: PlanOut, sel: SelectOut, by_ref: dict[str, Candidate]
) -> list[solver.Shot]:
    """The selector's picks as solver shots, in beat and pick order."""
    beat_index = {b.beat_id: i for i, b in enumerate(plan.beats)}
    shots: list[solver.Shot] = []
    for b in sel.beats:
        for i, x in enumerate(b.selections):
            cand = by_ref[x.segment_id]
            shots.append(
                solver.Shot(
                    cand=cand,
                    beat_id=b.beat_id,
                    beat_index=beat_index[b.beat_id],
                    order=i,
                    role=x.role,
                    priority=x.priority,
                    length=x.length,
                    # "dialogue" on a clip without speech means its natural sound
                    audio_intent=(
                        "natural_sound"
                        if x.audio_intent == "dialogue" and not cand.has_speech
                        else x.audio_intent
                    ),
                    reason=x.reason,
                    alternatives=[a.model_dump() for a in x.alternatives],
                )
            )
    return shots


def board_shot(sh: solver.Shot, rate: str) -> dict[str, Any]:
    """A pick as the storyboard keeps it (``draft.BoardShot``)."""
    return {
        "ref": sh.selection_ref,
        "segment_id": sh.cand.ref,
        "role": sh.role,
        "priority": sh.priority,
        "length": sh.length,
        "audio_intent": sh.audio_intent,
        "reason": sh.reason,
        "alternatives": sh.alternatives,
        "locked": sh.locked,
        "pin": None
        if sh.pin is None
        else {
            "segment_id": sh.cand.ref,
            "source_in": {"ticks": sh.pin[0], "tb": sh.cand.tb},
            "source_out": {"ticks": sh.pin[1], "tb": sh.cand.tb},
            "duration": {"frames": sh.pin[2], "rate": rate},
        },
    }


def lock_budget(shots: list[solver.Shot], target: int, tolerance: int) -> dict[str, Any]:
    """What the locked shots take of the target (S14 and S16's infeasible-locks warning):
    their frames, and how far they go past the longest edit allowed (0 when they fit)."""
    frames = sum(sh.pin[2] for sh in shots if sh.pin is not None)
    return {
        "shots": sum(1 for sh in shots if sh.locked),
        "pinned": sum(1 for sh in shots if sh.pin is not None),
        "frames": frames,  # pinned shots only: a lock without a cut is not budgeted
        "over_frames": max(0, frames - (target + tolerance)),
    }


@dataclass
class Resolved:
    """A timed edit: its timeline, beats, metrics and findings (no AI fields)."""

    timeline: dict[str, Any]
    beats: list[dict[str, Any]]
    metrics: dict[str, Any]
    findings: list[critic.Finding]


def resolve(
    s: Session,
    req: EditRequest,
    inp: EditInputs,
    plan: PlanOut,
    shots: list[solver.Shot],
    rejected: set[int],
    *,
    user_order: bool = False,
    excluded: set[str] | frozenset[str] = frozenset(),
) -> Resolved:
    """Time ``shots`` (the selection, in order) against the request: fit to the target,
    order by chronology, refine each cut, fix jump cuts, backfill from alternatives and
    land on the target; then the critic's checks and the timeline. The solver times its
    own copies: ``shots`` are left as they were, so a caller can resolve them again.
    ``user_order``: the shots' own order (beats as given, shots as given within them)
    instead of the request's chronology, once the owner has rearranged the storyboard.
    ``excluded``: segment refs the owner took out, never brought back as alternatives."""
    # Shallow copies: they share ``cand``, ``alternatives`` and ``absorbed``, which nothing
    # here changes.
    shots = [dataclasses.replace(sh) for sh in shots]
    rate, pace, cands = inp.rate, inp.pace, inp.cands
    by_ref = {c.ref: c for c in cands}
    target = target_frames(req.duration_s, rate)
    tolerance = target * req.tolerance_pct // 100
    shares = {b.beat_id: b.share_percent for b in plan.beats}
    locks = lock_budget(shots, target, tolerance)
    fit = solver.fit(shots, shares, target, tolerance, pace, rate)
    ordered = solver.order_shots(fit.shots, "story" if user_order else req.chronology)
    cuts = [refiner.refine(sh, clip_context(s, sh.cand), pace, rate) for sh in ordered]
    spares = [(sh, clip_context(s, sh.cand)) for sh in fit.dropped]
    picks = [*shots, *(x for sh in shots for x in sh.absorbed)]
    chosen = {sh.cand.segment_id for sh in picks}
    for sh in shots:
        for alt in sh.alternatives:
            alt_cand = by_ref.get(alt["segment_id"])
            if alt_cand is None or alt_cand.segment_id in chosen or alt_cand.ref in excluded:
                continue
            chosen.add(alt_cand.segment_id)
            spare = solver.Shot(
                cand=alt_cand,
                beat_id=sh.beat_id,
                beat_index=sh.beat_index,
                order=sh.order,
                alt_of=sh.selection_ref,
                alt_index=sum(1 for sp, _ in spares if sp.alt_of == sh.selection_ref),
                role="b_roll",
                priority=1,
                length="medium",
                audio_intent="dialogue" if alt_cand.has_speech else "natural_sound",
                reason=f"Alternative to {sh.cand.ref}: {alt['why_not']}",
            )
            spares.append((spare, clip_context(s, alt_cand)))
    notes = list(fit.notes)
    if locks["over_frames"] > 0:
        notes.insert(0, f"locked shots exceed the target by {locks['over_frames']} frames")
    for _ in range(4):
        cuts, jump_notes = refiner.fix_jump_cuts(cuts, rate, pace)
        notes += jump_notes
        if sum(c.frames for c in cuts) < target - tolerance:
            cuts, fill_notes = refiner.backfill(
                cuts,
                spares,
                target,
                tolerance,
                pace,
                rate,
                chronological=not user_order and req.chronology in ("strict", "mostly"),
                by_order=user_order,
            )
            notes += fill_notes
        refiner.land_on_target(cuts, target, rate, pace)
        if not any(refiner.is_jump(a, b) for a, b in itertools.pairwise(cuts)):
            break
    notes += refiner.choose_transitions(cuts, req.transitions, rate)
    notes += refiner.split_dialogue(cuts, rate, pace)
    fit.shots = [c.shot for c in cuts]
    metrics, findings = critic.evaluate(
        cuts,
        target,
        tolerance,
        rate,
        rejected,
        {c.day for c in cands if c.day},
        [b.beat_id for b in plan.beats],
    )
    metrics["retrieval"] = inp.counts
    metrics["locks"] = locks
    metrics["solver"] = solver.describe(fit) | {"notes": notes}
    evts = refiner.events(cuts, rate)
    in_edit = [sh for c in cuts for sh in (c.shot, *c.merged_shots)]
    used = {sh.cand.segment_id for sh in in_edit}
    inserted = [sh for sh in in_edit if sh.alt_of is not None]
    selections = {
        sh.selection_ref: {
            "segment_id": sh.cand.ref,
            "beat_id": sh.beat_id,
            "role": sh.role,
            "priority": sh.priority,
            "length": sh.length,
            "audio_intent": sh.audio_intent,
            "reason": sh.reason,
            "alternatives": sh.alternatives,
            "used": sh.cand.segment_id in used,
            "alternative_to": sh.alt_of,
        }
        for sh in [*picks, *inserted]
    }
    beats = [
        {
            "beat_id": b.beat_id,
            "title": b.title,
            "intent": b.intent,
            "share_percent": b.share_percent,
            "pool": list(dict.fromkeys(b.candidates)),
            # The storyboard: the beat's picks in their order, dropped ones included.
            "shots": [board_shot(sh, rate) for sh in shots if sh.beat_id == b.beat_id],
        }
        for b in plan.beats
    ]
    timeline = {
        "rate": rate,
        "duration": {"frames": sum(c.frames for c in cuts), "rate": rate},
        "tracks": [{"kind": "video", "events": evts}],
        "selections": selections,
        "title": plan.title,
        "order": "user" if user_order else "request",
    }
    return Resolved(timeline, beats, metrics, findings)
