"""``edit.generate``: retrieval → planner → selector → solver → refiner → critic → version.

The AI calls go through ``AIClient`` (cached, budgeted, validated); identical inputs make
zero AI calls (M0 acceptance 5) and, when the latest version already has the same key, no
new version. ``--variant N`` forces fresh planner and selector takes. Every position comes
from the solver and refiner (invariant 5); the version row is the source of truth and the
JSON export is derived from it (invariant 7).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaic.ai.client import AIClient
from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
from mosaic.ai.prompts.selector.schema_v2 import Output as SelectOut
from mosaic.ai.registry import task_check_ready, task_choice
from mosaic.core.clock import now_iso
from mosaic.core.keys import artifact_key
from mosaic.core.settings import ProviderChoice
from mosaic.core.time import parse_rational
from mosaic.editing.request import (
    STORY_PRESETS,
    EditRequest,
    dominant_rate,
    pace_frames,
)
from mosaic.editing.resolve import (
    EditInputs,
    rejected_segments,
    resolve,
    shots_from_selection,
)
from mosaic.editing.retrieval import Candidate, retrieve
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.context import TripContext
from mosaic.library.context import load as load_context
from mosaic.storage import provenance
from mosaic.storage.artifacts import dumps_json
from mosaic.storage.config import NotConfiguredError
from mosaic.storage.models_project import (
    Asset,
    DeepReview,
    Disposition,
    Edit,
    EditVersion,
    TechMetric,
    TranscriptSegment,
    VisualObservation,
)

EDIT_VERSION = "edit/1"  # solver + refiner + critic algorithm version
PLANNER = ("planner", 2)  # v2: trip context (M1)
SELECTOR = ("selector", 2)
POOL_FACTOR = 3
PLANNER_MAX_TOKENS = 8000
SELECTOR_MAX_TOKENS = 16000


CAPABILITIES = ("planner", "selector")


def edit_inputs(s: Session, req: EditRequest) -> EditInputs:
    rate = req.fps or dominant_rate(
        (r, d, tb)
        for r, d, tb in s.execute(
            select(Asset.rate, Asset.duration_ticks, Asset.tb).where(Asset.kind == "video")
        )
    )
    pace = pace_frames(req.pace, rate, req.shot_lengths)
    cands, counts = retrieve(s, Fraction(pace.min) / parse_rational(rate), Fraction(req.duration_s))
    return EditInputs(rate, pace, cands, counts, _inputs_digest(s, cands), load_context(s))


def analysing(ctx: TaskContext) -> bool:
    """An analysis job of the project is active (S13's "Preliminary"; ADR 0047)."""
    return bool(ctx.store.jobs(ctx.project.id, True, kind="analysis", limit=1))


def edit_key(
    project_id: str, req: EditRequest, inp: EditInputs, choices: Mapping[str, ProviderChoice]
) -> str:
    """The edit's artifact key (invariant 9): equal keys mean the same plan and, through
    the AI cache, no AI call. Render-only fields are not part of it (ADR 0046)."""
    return artifact_key(
        "edit",
        project_id=project_id,
        inputs={
            "request": req.key_dump(),
            "candidates": inp.digest,
            "rate": inp.rate,
            "trip_context": inp.trip.digest(),
        },
        config={cap: [ch.provider, ch.model] for cap, ch in choices.items()}
        | {"prompts": [list(PLANNER), list(SELECTOR)]},
        version=EDIT_VERSION,
    )


# ------------------------------------------------------------------ contexts


def request_summary(req: EditRequest) -> str:
    return (
        f"{req.duration_s} s, story {req.story} ({STORY_PRESETS[req.story]}), "
        f"chronology {req.chronology}, pace {req.pace}"
    )


def planner_context(
    req: EditRequest, cands: list[Candidate], trip: TripContext | None = None
) -> dict[str, Any]:
    days = sorted({c.day for c in cands if c.day})
    return {
        "trip_context": (trip or TripContext()).prompt_text(),
        "request": request_summary(req),
        "instructions": req.instructions or "(none)",
        "days": ", ".join(f"day {d}" for d in days) or "unknown",
        "candidate_count": len(cands),
        "candidates": "\n".join(c.line() for c in cands),
        # structured copies for validation and the offline fake adapter
        "candidate_refs": [c.ref for c in cands],
        "speech_refs": [c.ref for c in cands if c.has_speech],
        "candidate_assets": {c.ref: c.asset_id for c in cands},
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
    req: EditRequest,
    plan: PlanOut,
    by_ref: dict[str, Candidate],
    pace_pref_s: Fraction,
    trip: TripContext | None = None,
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
        "trip_context": (trip or TripContext()).prompt_text(),
        "request": request_summary(req),
        "instructions": req.instructions or "(none)",
        "pace": f"{req.pace} (preferred shot about {float(pace_pref_s):.1f} s)",
        "beats": "\n\n".join(blocks),
        "beat_pools": pools,
        "speech_refs": [r for r, c in by_ref.items() if c.has_speech],
        "candidate_assets": {r: c.asset_id for r, c in by_ref.items()},
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
        for rev in session.execute(
            select(DeepReview.segment_id, DeepReview.provenance_id)
            .where(DeepReview.segment_id.in_(part))
            .order_by(DeepReview.segment_id)
        ):
            h.update(f"r{tuple(rev)};".encode())
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


def write_export(path: Path, payload: dict[str, Any]) -> None:
    """The derived JSON export (invariant 7), written atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(dumps_json(payload))
    tmp.replace(path)


# ---------------------------------------------------------------------- task


@task("edit.generate", checkpoint=True)
def generate_task(ctx: TaskContext) -> dict[str, Any]:
    edit_id = int(ctx.params["edit_id"])
    with ctx.project.db.session() as s:
        edit = s.get(Edit, edit_id)
        if edit is None:
            raise PermanentError(f"edit {edit_id} not found")
        req = EditRequest.model_validate(edit.request)
        inp = edit_inputs(s, req)
        rate, pace, cands, trip = inp.rate, inp.pace, inp.cands, inp.trip
        rejected = rejected_segments(s)
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
    choices = {cap: task_choice(ctx, cap) for cap in CAPABILITIES}
    key = edit_key(ctx.project.id, req, inp, choices)
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
                write_export(path, version_json(edit_row, latest))
            return {"edit_id": edit_id, "version": latest.version, "reused": True}

    by_ref = {c.ref: c for c in cands}
    preliminary = analysing(ctx)  # also checked at the end: either makes it preliminary
    client = AIClient(ctx)
    ctx.set_stage("planning")
    pctx = planner_context(req, cands, trip)
    plan_res = client.structured(
        "planner",
        *PLANNER,
        pctx,
        max_tokens=PLANNER_MAX_TOKENS,
        variant=req.variant,
        validate=lambda a: check_plan(a, set(by_ref)),
    )
    plan = plan_res.data
    assert isinstance(plan, PlanOut)
    pref_s = Fraction(pace.preferred) / parse_rational(rate)
    sctx = selector_context(req, plan, by_ref, pref_s, trip)
    ctx.set_stage("selecting shots")
    sel_res = client.structured(
        "selector",
        *SELECTOR,
        sctx,
        max_tokens=SELECTOR_MAX_TOKENS,
        variant=req.variant,
        validate=lambda a: check_selection(a, plan, set(by_ref)),
    )
    sel = sel_res.data
    assert isinstance(sel, SelectOut)

    shots = shots_from_selection(plan, sel, by_ref)
    ctx.set_stage("timing")
    with ctx.project.db.session() as s:
        done = resolve(s, req, inp, plan, shots, rejected)
    metrics = done.metrics
    # Made while the library was still being analysed.
    metrics["preliminary"] = preliminary or analysing(ctx)
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
            beats=done.beats,
            timeline=done.timeline,
            metrics=metrics,
            findings=[f.as_json() for f in done.findings],
            provenance_id=prov,
            created_at=now_iso(),
        )
        s.add(row)
        s.flush()
        edit_row = s.get(Edit, edit_id)
        assert edit_row is not None
        payload = version_json(edit_row, row)
    path = export_path(ctx.project.workspace, edit_id, number)
    write_export(path, payload)
    return {
        "edit_id": edit_id,
        "version": number,
        "events": len(done.timeline["tracks"][0]["events"]),
        "blocking_ok": metrics["blocking_ok"],
        "export": str(path),
    }
