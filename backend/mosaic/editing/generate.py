"""``edit.generate``: retrieval → planner → selector → solver → refiner → critic → version.

The AI calls go through ``AIClient`` (cached, budgeted, validated); identical inputs make
zero AI calls (M0 acceptance 5) and, when the latest version already has the same key, no
new version. ``--variant N`` forces fresh planner and selector takes. Every position comes
from the solver and refiner (invariant 5); the version row is the source of truth and the
JSON export is derived from it (invariant 7).
"""

from __future__ import annotations

import hashlib
import itertools
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaic.ai.client import AIClient
from mosaic.ai.prompts.planner.schema_v1 import Output as PlanOut
from mosaic.ai.prompts.selector.schema_v1 import Output as SelectOut
from mosaic.ai.registry import task_check_ready, task_choice
from mosaic.core.clock import now_iso
from mosaic.core.keys import artifact_key
from mosaic.core.time import parse_rational
from mosaic.editing import critic, refiner, solver
from mosaic.editing.request import (
    STORY_PRESETS,
    EditRequest,
    dominant_rate,
    pace_frames,
    target_frames,
)
from mosaic.editing.retrieval import Candidate, retrieve
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import PermanentError, task
from mosaic.storage import provenance
from mosaic.storage.artifacts import dumps_json
from mosaic.storage.config import NotConfiguredError
from mosaic.storage.models_project import (
    Asset,
    Disposition,
    Edit,
    EditVersion,
    TechMetric,
    TranscriptSegment,
    TranscriptWord,
    VisualObservation,
)

EDIT_VERSION = "edit/1"  # solver + refiner + critic algorithm version
PLANNER = ("planner", 1)
SELECTOR = ("selector", 1)
POOL_FACTOR = 3


# ------------------------------------------------------------------ contexts


def request_summary(req: EditRequest) -> str:
    return (
        f"{req.duration_s} s, story {req.story} ({STORY_PRESETS[req.story]}), "
        f"chronology {req.chronology}, pace {req.pace}"
    )


def planner_context(req: EditRequest, cands: list[Candidate]) -> dict[str, Any]:
    days = sorted({c.day for c in cands if c.day})
    return {
        "request": request_summary(req),
        "instructions": req.instructions or "(none)",
        "days": ", ".join(f"day {d}" for d in days) or "unknown",
        "candidate_count": len(cands),
        "candidates": "\n".join(c.line() for c in cands),
        # structured copies for validation and the offline fake adapter
        "candidate_refs": [c.ref for c in cands],
        "speech_refs": [c.ref for c in cands if c.has_speech],
        "duration_s": req.duration_s,
    }


def check_plan(answer: PlanOut, refs: set[str]) -> list[str]:
    errors = []
    ids = [b.beat_id for b in answer.beats]
    if len(set(ids)) != len(ids):
        errors.append("beat_id values must be unique")
    total = sum(b.share_percent for b in answer.beats)
    if not 95 <= total <= 105:
        errors.append(f"share_percent adds up to {total}; it must add up to 100")
    for b in answer.beats:
        unknown = [r for r in b.candidates if r not in refs]
        if unknown:
            errors.append(f"{b.beat_id}: unknown clip ids {', '.join(unknown[:5])}")
    return errors


def selector_context(
    req: EditRequest, plan: PlanOut, by_ref: dict[str, Candidate], pace_pref_s: Fraction
) -> dict[str, Any]:
    total = sum(b.share_percent for b in plan.beats) or 1
    blocks = []
    pools = []
    for b in plan.beats:
        seconds = Fraction(req.duration_s * b.share_percent, total)
        shots = max(1, round(seconds / pace_pref_s))
        pool = [r for r in dict.fromkeys(b.candidates) if r in by_ref]
        pools.append({"beat_id": b.beat_id, "pool": pool, "shots": shots})
        lines = "\n".join(by_ref[r].detail() for r in pool)
        blocks.append(
            f"## {b.beat_id}: {b.title}\nIntent: {b.intent}\n"
            f"Target: about {round(seconds)} s, about {shots} shots\nPool:\n{lines}"
        )
    return {
        "request": request_summary(req),
        "instructions": req.instructions or "(none)",
        "pace": f"{req.pace} (preferred shot about {float(pace_pref_s):.1f} s)",
        "beats": "\n\n".join(blocks),
        "beat_pools": pools,
        "speech_refs": [r for r, c in by_ref.items() if c.has_speech],
    }


def check_selection(answer: SelectOut, plan: PlanOut, refs: set[str]) -> list[str]:
    errors = []
    wanted = [b.beat_id for b in plan.beats]
    got = [b.beat_id for b in answer.beats]
    if sorted(got) != sorted(wanted):
        errors.append(f"return exactly the beats {', '.join(wanted)}; got {', '.join(got)}")
    pools = {b.beat_id: set(b.candidates) for b in plan.beats}
    seen: set[str] = set()
    for b in answer.beats:
        for s in b.selections:
            if s.segment_id not in refs:
                errors.append(f"{b.beat_id}: {s.segment_id} is not a candidate")
            elif s.segment_id not in pools.get(b.beat_id, set()):
                errors.append(f"{b.beat_id}: {s.segment_id} is not in this beat's pool")
            if s.segment_id in seen:
                errors.append(f"{s.segment_id} is used more than once")
            seen.add(s.segment_id)
            for alt in s.alternatives:
                if alt.segment_id not in refs:
                    errors.append(
                        f"{s.segment_id}: alternative {alt.segment_id} is not a candidate"
                    )
    return errors


# ------------------------------------------------------------------- loading


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


def _inputs_digest(session: Session, cands: list[Candidate]) -> str:
    """Everything the candidates were derived from: observations and dispositions."""
    h = hashlib.sha256()
    for c in cands:
        h.update(
            f"{c.segment_id}:{c.start}:{c.end}:{c.usable_start}:{c.usable_end}:{c.status}:"
            f"{c.user_use}:{c.group_id};".encode()
        )
    ids = [c.segment_id for c in cands]
    for chunk in range(0, len(ids), 500):
        part = ids[chunk : chunk + 500]
        for row in session.execute(
            select(VisualObservation.segment_id, VisualObservation.provenance_id)
            .where(VisualObservation.segment_id.in_(part))
            .order_by(VisualObservation.segment_id)
        ):
            h.update(f"v{tuple(row)};".encode())
        for drow in session.execute(
            select(
                Disposition.segment_id,
                Disposition.source,
                Disposition.status,
                Disposition.updated_at,
            )
            .where(Disposition.segment_id.in_(part))
            .order_by(Disposition.segment_id, Disposition.source)
        ):
            h.update(f"d{tuple(drow)};".encode())
    # The refiner also reads words, sentences and motion of these assets.
    assets = sorted({c.asset_id for c in cands})
    for pid in session.scalars(
        select(TranscriptSegment.provenance_id)
        .where(TranscriptSegment.asset_id.in_(assets))
        .distinct()
        .order_by(TranscriptSegment.provenance_id)
    ):
        h.update(f"t{pid};".encode())
    for pid in session.scalars(
        select(TechMetric.provenance_id)
        .where(TechMetric.asset_id.in_(assets), TechMetric.name == "motion")
        .distinct()
        .order_by(TechMetric.provenance_id)
    ):
        h.update(f"m{pid};".encode())
    return h.hexdigest()


def export_path(workspace: Path, edit_id: int, version: int) -> Path:
    return workspace / "edits" / f"edt_{edit_id:04d}" / f"v{version:03d}.json"


def version_json(edit: Edit, v: EditVersion) -> dict[str, Any]:
    return {
        "format": "mosaic.edit/1",
        "edit_id": f"edt_{edit.id:04d}",
        "name": edit.name,
        "version": v.version,
        "parent_version": v.parent_version,
        "creator": v.creator,
        "reason": v.reason,
        "created_at": v.created_at,
        "key": v.key,
        "provenance_id": v.provenance_id,
        "request": v.request,
        "rate": v.rate,
        "beats": v.beats,
        "timeline": v.timeline,
        "metrics": v.metrics,
        "findings": v.findings,
    }


def _write_export(path: Path, payload: dict[str, Any]) -> None:
    """The derived JSON export (invariant 7), written atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(dumps_json(payload))
    tmp.replace(path)


# ---------------------------------------------------------------------- task


@task("edit.generate")
def generate_task(ctx: TaskContext) -> dict[str, Any]:
    edit_id = int(ctx.params["edit_id"])
    with ctx.project.db.session() as s:
        edit = s.get(Edit, edit_id)
        if edit is None:
            raise PermanentError(f"edit {edit_id} not found")
        req = EditRequest.model_validate(edit.request)
        rate = req.fps or dominant_rate(
            (r, d, tb)
            for r, d, tb in s.execute(
                select(Asset.rate, Asset.duration_ticks, Asset.tb).where(Asset.kind == "video")
            )
        )
        pace = pace_frames(req.pace, rate)
        target = target_frames(req.duration_s, rate)
        tolerance = target * req.tolerance_pct // 100
        cands, counts = retrieve(
            s, Fraction(pace.min) / parse_rational(rate), Fraction(req.duration_s)
        )
        digest = _inputs_digest(s, cands)
        rejected = {
            sid
            for sid in s.scalars(
                select(Disposition.segment_id).where(
                    Disposition.status == "REJECT", Disposition.segment_id.is_not(None)
                )
            )
            if sid is not None
        }
        users = {
            d.segment_id: d.status
            for d in s.scalars(select(Disposition).where(Disposition.source == "user"))
        }
    rejected = {sid for sid in rejected if users.get(sid, "REJECT") == "REJECT"}
    if not cands:
        raise PermanentError(
            "no usable clips: analyze the folder first (`mosaic analyze`), or every clip "
            "was rejected or is shorter than the minimum shot"
        )
    try:
        task_check_ready(ctx, "planner")
        task_check_ready(ctx, "selector")
    except NotConfiguredError as exc:
        raise PermanentError(str(exc)) from None
    choices = {cap: task_choice(ctx, cap) for cap in ("planner", "selector")}
    key = artifact_key(
        "edit",
        project_id=ctx.project.id,
        inputs={"request": req.model_dump(mode="json"), "candidates": digest, "rate": rate},
        config={cap: [ch.provider, ch.model] for cap, ch in choices.items()}
        | {"prompts": [list(PLANNER), list(SELECTOR)]},
        version=EDIT_VERSION,
    )
    with ctx.project.db.session() as s:
        latest = s.scalar(
            select(EditVersion)
            .where(EditVersion.edit_id == edit_id)
            .order_by(EditVersion.version.desc())
            .limit(1)
        )
        if latest is not None and latest.key == key:
            path = export_path(ctx.project.workspace, edit_id, latest.version)
            if not path.is_file():  # e.g. a crash between the commit and the file write
                edit_row = s.get(Edit, edit_id)
                assert edit_row is not None
                _write_export(path, version_json(edit_row, latest))
            return {"edit_id": edit_id, "version": latest.version, "reused": True}

    by_ref = {c.ref: c for c in cands}
    client = AIClient(ctx)
    ctx.set_stage("planning")
    pctx = planner_context(req, cands)
    plan_res = client.structured(
        "planner",
        *PLANNER,
        pctx,
        max_tokens=8000,
        variant=req.variant,
        validate=lambda a: check_plan(a, set(by_ref)),
    )
    plan = plan_res.data
    assert isinstance(plan, PlanOut)
    pref_s = Fraction(pace.preferred) / parse_rational(rate)
    sctx = selector_context(req, plan, by_ref, pref_s)
    ctx.set_stage("selecting shots")
    sel_res = client.structured(
        "selector",
        *SELECTOR,
        sctx,
        max_tokens=16000,
        variant=req.variant,
        validate=lambda a: check_selection(a, plan, set(by_ref)),
    )
    sel = sel_res.data
    assert isinstance(sel, SelectOut)

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
    shares = {b.beat_id: b.share_percent for b in plan.beats}
    ctx.set_stage("timing")
    fit = solver.fit(shots, shares, target, tolerance, pace, rate)
    ordered = solver.order_shots(fit.shots, req.chronology)
    with ctx.project.db.session() as s:
        cuts = [refiner.refine(sh, clip_context(s, sh.cand), pace, rate) for sh in ordered]
        spares = [(sh, clip_context(s, sh.cand)) for sh in fit.dropped]
        chosen = {sh.cand.segment_id for sh in shots}
        for sh in shots:
            for alt in sh.alternatives:
                alt_cand = by_ref.get(alt["segment_id"])
                if alt_cand is None or alt_cand.segment_id in chosen:
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
                chronological=req.chronology in ("strict", "mostly"),
            )
            notes += fill_notes
        refiner.land_on_target(cuts, target, rate, pace)
        if not any(refiner.is_jump(a, b) for a, b in itertools.pairwise(cuts)):
            break
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
    metrics["retrieval"] = counts
    metrics["solver"] = solver.describe(fit) | {"notes": notes}
    metrics["ai"] = {
        "planner": {
            "provider": plan_res.provider,
            "model": plan_res.model,
            "cached": plan_res.cached,
        },
        "selector": {
            "provider": sel_res.provider,
            "model": sel_res.model,
            "cached": sel_res.cached,
        },
        "cost_usd": round(plan_res.cost_usd + sel_res.cost_usd, 6),
    }
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
        for sh in [*shots, *inserted]
    }
    beats = [
        {
            "beat_id": b.beat_id,
            "title": b.title,
            "intent": b.intent,
            "share_percent": b.share_percent,
            "pool": list(dict.fromkeys(b.candidates)),
        }
        for b in plan.beats
    ]
    timeline = {
        "rate": rate,
        "duration": {"frames": sum(c.frames for c in cuts), "rate": rate},
        "tracks": [{"kind": "video", "events": evts}],
        "selections": selections,
        "title": plan.title,
    }
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="edit",
                algorithm_version=EDIT_VERSION,
                prompt_version=f"planner/v{PLANNER[1]},selector/v{SELECTOR[1]}",
                input_keys=[key, f"prov:{plan_res.provenance_id}", f"prov:{sel_res.provenance_id}"],
            ),
        )
        number = (
            s.scalar(select(func.max(EditVersion.version)).where(EditVersion.edit_id == edit_id))
            or 0
        ) + 1
        row = EditVersion(
            edit_id=edit_id,
            version=number,
            parent_version=number - 1 if number > 1 else None,
            creator="ai",
            reason="generate" if number == 1 else "regenerate",
            key=key,
            request=req.model_dump(mode="json"),
            rate=rate,
            beats=beats,
            timeline=timeline,
            metrics=metrics,
            findings=[f.as_json() for f in findings],
            provenance_id=prov,
            created_at=now_iso(),
        )
        s.add(row)
        s.flush()
        edit_row = s.get(Edit, edit_id)
        assert edit_row is not None
        payload = version_json(edit_row, row)
    path = export_path(ctx.project.workspace, edit_id, number)
    _write_export(path, payload)
    return {
        "edit_id": edit_id,
        "version": number,
        "events": len(evts),
        "blocking_ok": metrics["blocking_ok"],
        "export": str(path),
    }
