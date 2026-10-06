"""L3 deep review (ANALYSIS_MODES.md §1, Thorough): candidates only, full resolution.

A candidate is a segment whose effective disposition is not REJECT and that is the
recommended pick of its similarity group (or one the user marked USE). For each, a few
frames are cut from the **original** file exactly like the renderer cuts it (fast seek,
``-copyts``, ``trim`` at the absolute stream time) at the reviewer's largest useful size
— a far-away aircraft is a speck in a 392 px mosaic tile but visible here — and the
``review`` prompt, with the trip context, returns one observation. One AI call per
candidate (M1 acceptance 5). The observation is stored in ``deep_review`` and takes
precedence over the L2 one in dispositions, retrieval and reports.

A review is keyed by everything it depends on (segment, frame times, source files,
image size, prompt, reviewer model, trip context); a candidate whose stored key matches
is skipped without decoding (invariant 9). A frame that cannot be decoded skips that
candidate with a reason; it never fails the task (invariant 14).

Scope: a project, a trip day, or explicit segments.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mosaic.ai.client import AIClient
from mosaic.ai.prompts.review.schema_v1 import Output
from mosaic.ai.registry import limits_for, task_check_ready, task_choice
from mosaic.ai.types import ImageInput
from mosaic.core.keys import artifact_key
from mosaic.core.time import format_display, parse_rational
from mosaic.editing.retrieval import capture_dates, trip_day
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass, TaskSpec
from mosaic.jobs.registry import SkipTask, task
from mosaic.library import devices as _devices  # noqa: F401 - registers before L3
from mosaic.library import moments as _moments  # noqa: F401 - registers before L3
from mosaic.library.context import load as load_context
from mosaic.library.dispositions import effective
from mosaic.library.summaries import SUMMARIES_STAGE, summaries_spec
from mosaic.media import inventory
from mosaic.media.ffmpeg.builders import still_frame
from mosaic.media.ffmpeg.render import SEEK_MARGIN
from mosaic.media.ffmpeg.run import FFmpegError, run
from mosaic.media.tools import media_tools
from mosaic.storage.config import NotConfiguredError
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    DeepReview,
    MediaFile,
    MediaStream,
    Mosaic,
    MosaicTile,
    Segment,
    VisualObservation,
)

PROMPT = ("review", 1)
REVIEW_VERSION = "review-task/1"
FRAMES = 3  # frames per segment, spread over the usable range
MAX_TOKENS = 3000

Source = tuple[str, int, int, Fraction, str]  # path, logical start, duration, video start s, fp


def candidate_ids(session: Session, asset_id: int) -> list[int]:
    """L3 candidates of one asset: not REJECT, best of their similarity group (or user USE)."""
    segs = list(
        session.scalars(
            select(Segment).where(Segment.asset_id == asset_id).order_by(Segment.start_ticks)
        )
    )
    disp = effective(session, [g.id for g in segs])
    out = []
    for g in segs:
        d = disp.get(g.id)
        if d is not None and d.status == "REJECT":
            continue
        user_use = d is not None and d.source == "user" and d.status == "USE"
        if g.similarity_group_id is not None and not g.group_best and not user_use:
            continue
        out.append(g.id)
    return out


def frame_times(seg: Segment, n: int = FRAMES) -> list[int]:
    """``n`` instants spread over the usable range (ticks), inside it."""
    a, b = seg.usable_start_ticks, seg.usable_end_ticks
    if b <= a:
        a, b = seg.start_ticks, seg.end_ticks
    span = b - a
    return [a + span * (2 * i + 1) // (2 * n) for i in range(n)]


def check_best_frame(answer: Any, frames: int) -> list[str]:
    best = int(answer.best_frame[1:])
    if not 1 <= best <= frames:
        return [f"best_frame {answer.best_frame} does not exist; use F1 to F{frames}"]
    return []


def _sources(session: Session, asset: Asset) -> list[Source]:
    out: list[Source] = []
    for path, start, dur, pts, stb, fp in session.execute(
        select(
            MediaFile.rel_path,
            AssetFile.logical_start_ticks,
            AssetFile.duration_ticks,
            MediaStream.start_pts,
            MediaStream.time_base,
            MediaFile.fingerprint,
        )
        .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
        .join(MediaStream, MediaStream.media_file_id == MediaFile.id)
        .where(
            AssetFile.asset_id == asset.id,
            MediaStream.stream_index == asset.video_stream_index,
        )
        .order_by(AssetFile.order)
    ):
        out.append((str(path), int(start), int(dur), Fraction(pts) * parse_rational(stb), str(fp)))
    return out


def locate(sources: list[Source], ticks: int, tb: Fraction) -> tuple[str, Fraction, Fraction]:
    """(file, absolute stream seconds, input seek seconds) for logical ``ticks``: a file's
    logical 0 is its first video PTS (as for proxies and renders)."""
    chosen = sources[-1]
    for src in sources:
        if src[1] <= ticks < src[1] + src[2]:
            chosen = src
            break
    path, start, _, video_start, _ = chosen
    local = Fraction(ticks - start) * tb
    return path, video_start + local, max(Fraction(0), local - SEEK_MARGIN)


def review_key(
    project_id: str,
    seg: Segment,
    times: list[int],
    fingerprints: list[str],
    max_px: int,
    choice: tuple[str, str],
    context_digest: str,
    l2_provenance: int | None,
    hdr: bool,
) -> str:
    return artifact_key(
        "review",
        project_id=project_id,
        inputs={
            "segment": [seg.id, seg.provenance_id],
            "frames": times,
            "files": fingerprints,
            "context": context_digest,
            "l2": l2_provenance,  # the prompt quotes the L2 description
        },
        config={
            "max_px": max_px,
            "tonemap": hdr,
            "provider": list(choice),
            "prompt": list(PROMPT),
        },
        version=REVIEW_VERSION,
    )


# ------------------------------------------------------------------------ task


@task("library.review")
def review_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = int(ctx.params["asset_id"])
    wanted = set(ctx.params.get("segment_ids") or [])
    try:
        task_check_ready(ctx, "reviewer")
    except NotConfiguredError as exc:
        raise SkipTask(f"deep review skipped: {exc}") from None
    choice = task_choice(ctx, "reviewer")
    max_px = limits_for(choice).max_image_px
    binaries, caps = media_tools()
    client = AIClient(ctx)
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        if asset is None or asset.tb is None or asset.video_stream_index is None:
            raise SkipTask("not a video asset")
        tb_text, stream = asset.tb, asset.video_stream_index
        # An untone-mapped HDR frame is still reviewable; never fail for a missing filter.
        hdr = asset.color_hint in ("hlg", "pq") and caps.can_tonemap
        trip = load_context(s)
        sources = _sources(s, asset)
        ids = [i for i in candidate_ids(s, asset_id) if not wanted or i in wanted]
        segs = {g.id: g for g in s.scalars(select(Segment).where(Segment.id.in_(ids)))}
        l2 = {
            o.segment_id: (o.data, o.provenance_id)
            for o in s.scalars(
                select(VisualObservation).where(VisualObservation.segment_id.in_(ids))
            )
        }
        stored = {
            r.segment_id: r.key
            for r in s.scalars(select(DeepReview).where(DeepReview.segment_id.in_(ids)))
        }
    if not sources:
        raise SkipTask("no video stream rows for this asset")
    tb = parse_rational(tb_text)
    fingerprints = [src[4] for src in sources]
    reviewed = cached = unchanged = 0
    skipped: list[str] = []
    cost = 0.0
    for sid in ids:
        ctx.check_cancelled()
        seg = segs[sid]
        times = frame_times(seg)
        key = review_key(
            ctx.project.id,
            seg,
            times,
            fingerprints,
            max_px,
            (choice.provider, choice.model),
            trip.digest(),
            l2[sid][1] if sid in l2 else None,
            hdr,
        )
        if stored.get(sid) == key:
            unchanged += 1
            continue
        images: list[ImageInput] = []
        lines: list[str] = []
        try:
            for n, t in enumerate(times, 1):
                rel, at, seek = locate(sources, t, tb)
                cmd = still_frame(ctx.project.root / rel, stream, at, seek, max_px, hdr)
                jpeg = run(binaries, cmd).stdout
                with Image.open(io.BytesIO(jpeg)) as im:
                    w, h = im.size
                images.append(ImageInput(jpeg, "image/jpeg", w, h))
                lines.append(f"F{n}: {format_display(Fraction(t) * tb)}")
        except (FFmpegError, UnidentifiedImageError, OSError) as exc:
            skipped.append(f"seg_{sid:06d}: frame not decodable ({type(exc).__name__})")
            continue
        context = {
            "trip_context": trip.prompt_text(),
            "l2_description": (l2[sid][0] if sid in l2 else {}).get("description", "(none)"),
            "duration": format_display(
                Fraction(seg.usable_end_ticks - seg.usable_start_ticks) * tb
            ),
            "frame_list": "\n".join(lines),
        }
        count = len(images)

        def validate(answer: Any, count: int = count) -> list[str]:
            return check_best_frame(answer, count)

        result = client.structured(
            "reviewer", *PROMPT, context, images, max_tokens=MAX_TOKENS, validate=validate
        )
        answer = result.data
        assert isinstance(answer, Output)
        data = answer.model_dump(mode="json")
        best = int(answer.best_frame[1:]) - 1
        data["best_frame"] = {
            "frame": answer.best_frame,
            "time": {"ticks": times[best], "tb": tb_text},
        }
        data["frames"] = [{"ticks": t, "tb": tb_text} for t in times]
        with ctx.write() as s:
            s.execute(delete(DeepReview).where(DeepReview.segment_id == sid))
            s.add(
                DeepReview(
                    segment_id=sid,
                    key=key,
                    data=data,
                    context_digest=trip.digest(),
                    provenance_id=result.provenance_id,
                )
            )
        reviewed += 1
        cached += int(result.cached)
        cost += result.cost_usd
    return {
        "reviewed": reviewed,
        "unchanged": unchanged,
        "cached": cached,
        "skipped": skipped,
        "cost_usd": round(cost, 6),
    }


# --------------------------------------------------------------------- deepen
# Deepening a scope (the trip, some days, a selection) only *adds* levels to what is
# there: L2 for clips that have none, then (target Thorough) L3 for the candidates. It
# never recomputes L0/L1 (ANALYSIS_MODES §3, M1 acceptance 5, ADR 0020).

TARGETS = ("balanced", "thorough")


@dataclass(frozen=True)
class DeepenScope:
    """The trip (both empty), some trip days, or a selection of segments."""

    days: tuple[int, ...] = ()
    segment_ids: tuple[int, ...] = ()

    def as_params(self) -> dict[str, Any]:
        return {"days": list(self.days), "segment_ids": list(self.segment_ids)}

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> DeepenScope:
        return cls(tuple(params.get("days") or ()), tuple(params.get("segment_ids") or ()))


def scope_segments(session: Session, scope: DeepenScope) -> dict[int, list[int]]:
    """Asset id → every segment in scope (any disposition), in time order. Days are
    numbered exactly as the editor numbers them (``retrieval.trip_day``)."""
    assets = list(session.scalars(select(Asset).where(Asset.kind == "video").order_by(Asset.id)))
    first = min(capture_dates(assets).values(), default=None)
    wanted = set(scope.segment_ids)
    days = set(scope.days)
    out: dict[int, list[int]] = {}
    for a in assets:
        segs = list(
            session.scalars(
                select(Segment).where(Segment.asset_id == a.id).order_by(Segment.start_ticks)
            )
        )
        if wanted:
            segs = [g for g in segs if g.id in wanted]
        if days and a.tb is None:
            continue  # no timeline: it cannot be placed on a day
        if days and a.tb is not None:
            rate = parse_rational(a.tb)
            segs = [
                g
                for g in segs
                if trip_day(a.capture_time, Fraction(g.start_ticks) * rate, first) in days
            ]
        if segs:
            out[a.id] = [g.id for g in segs]
    return out


def plan_deepen(
    session: Session, scope: DeepenScope | None = None
) -> tuple[dict[int, list[int]], list[int]]:
    """(asset id → L3 candidates in scope, requested ids that are not candidates)."""
    scope = scope or DeepenScope()
    plan: dict[int, list[int]] = {}
    found: set[int] = set()
    for aid, ids in scope_segments(session, scope).items():
        in_scope = set(ids)
        cands = [i for i in candidate_ids(session, aid) if i in in_scope]
        found |= set(cands)
        if cands:
            plan[aid] = cands
    return plan, sorted(set(scope.segment_ids) - found)


def l2_missing(session: Session, scoped: dict[int, list[int]]) -> list[int]:
    """Assets with segments in scope but no L2: no contact sheets at all, or sheets whose
    segments have no observation (a run without L2, or one stopped part-way)."""
    out = []
    for aid, ids in scoped.items():
        tiled = set(
            session.scalars(
                select(MosaicTile.segment_id)
                .join(Mosaic, Mosaic.id == MosaicTile.mosaic_id)
                .where(Mosaic.asset_id == aid)
            )
        )
        if not tiled:
            out.append(aid)
            continue
        wanted = [i for i in ids if i in tiled]
        observed = set(
            session.scalars(
                select(VisualObservation.segment_id).where(VisualObservation.segment_id.in_(wanted))
            )
        )
        if set(wanted) - observed:
            out.append(aid)
    return out


def review_tasks(plan: dict[int, list[int]]) -> list[TaskSpec]:
    """One review task per asset, then dispositions (which merge the reviews)."""
    tasks = [
        TaskSpec(
            kind="library.review",
            stage="deep review",
            resource_class=ResourceClass.AI_API,
            params={"asset_id": aid, "segment_ids": ids},
            label=f"deep review ast_{aid:04d} ({len(ids)})",
        )
        for aid, ids in plan.items()
    ]
    tasks.append(_dispositions(deps=[*range(len(tasks))]))
    # Reviews change descriptions and interest: refresh the summaries that use them.
    tasks.append(summaries_spec(deps=[len(tasks) - 1]))
    return tasks


def _dispositions(deps: list[int | tuple[str, int]]) -> TaskSpec:
    return TaskSpec(
        kind="library.dispositions",
        stage="dispositions",
        resource_class=ResourceClass.CPU,
        label="dispositions",
        deps=deps,
    )


def l2_tasks(asset_ids: list[int]) -> list[TaskSpec]:
    """Contact sheets and vision for each asset, then dispositions."""
    tasks: list[TaskSpec] = []
    for aid in asset_ids:
        tasks.append(
            TaskSpec(
                kind="library.mosaics",
                stage="mosaics",
                resource_class=ResourceClass.CPU,
                params={"asset_id": aid},
                label=f"mosaics ast_{aid:04d}",
            )
        )
        tasks.append(
            TaskSpec(
                kind="library.vision",
                stage="vision",
                resource_class=ResourceClass.AI_API,
                params={"asset_id": aid},
                label=f"vision ast_{aid:04d}",
                deps=[len(tasks) - 1],
            )
        )
    tasks.append(_dispositions(deps=[*range(len(tasks))]))
    return tasks


@dataclass(frozen=True)
class DeepenRun:
    job: int | None  # None: nothing to add in this scope
    candidates: int  # L3 candidates known now (more may follow the L2 it adds)
    l2_assets: list[int]  # clips that get L2 first
    dropped: list[int]  # requested segment ids that are not L3 candidates


def submit_deepen(
    executor: Any,
    principal: Any,
    project: Any,
    scope: DeepenScope | None = None,
    *,
    target: str = "thorough",
    cost_limit_usd: float | None = None,
) -> DeepenRun:
    """Start a deepening job for ``scope``: L2 where it is missing, then (``thorough``)
    an L3 review of the candidates."""
    from mosaic.core.modes import resolve
    from mosaic.jobs.model import JobSpec
    from mosaic.media.pipeline import job_cost_limit

    if target not in TARGETS:
        raise ValueError(f"deepen target must be one of {', '.join(TARGETS)}")
    scope = scope or DeepenScope()
    with project.db.session() as s:
        scoped = scope_segments(s, scope)
        missing = l2_missing(s, scoped)
        plan, dropped = plan_deepen(s, scope)
    if missing:
        # Their candidates are unknown until L2 and dispositions run: requested ids in
        # those clips are not "dropped" yet.
        pending = {i for aid in missing for i in scoped[aid]}
        dropped = [i for i in dropped if i not in pending]
    count = sum(len(v) for v in plan.values())
    tasks: list[TaskSpec] = []
    if missing:
        tasks = l2_tasks(missing)
        if target == "balanced":
            tasks.append(summaries_spec(deps=[len(tasks) - 1]))
        if target == "thorough":
            tasks.append(
                TaskSpec(
                    kind="analysis.deepen",
                    stage="deep review",
                    resource_class=ResourceClass.CPU,
                    params=scope.as_params(),
                    label="deep review",
                    deps=[len(tasks) - 1],
                )
            )
    elif target == "thorough" and plan:
        tasks = review_tasks(plan)
    if not tasks:
        return DeepenRun(None, count, missing, dropped)
    job = executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="deepen",
            params={
                **scope.as_params(),
                "target": target,
                "mode_config": resolve(target).model_dump(mode="json"),
            },
            cost_limit_usd=job_cost_limit(principal) if cost_limit_usd is None else cost_limit_usd,
            tasks=tasks,
        ),
    )
    return DeepenRun(job, count, missing, dropped)


@task("analysis.deepen")
def deepen_stage(ctx: TaskContext) -> dict[str, Any]:
    """L3 after dispositions: review every candidate in the task's scope (the whole
    project in a Thorough run; unchanged reviews are skipped by key), then re-run
    dispositions so they merge the reviews."""
    with ctx.project.db.session() as s:
        plan, _ = plan_deepen(s, DeepenScope.from_params(ctx.params))
    if not plan:
        ctx.spawn([summaries_spec()])  # nothing to review: summaries still end the chain
        return {"candidates": 0, "assets": 0}
    ctx.spawn(review_tasks(plan))
    return {"candidates": sum(len(v) for v in plan.values()), "assets": len(plan)}


inventory.PROJECT_STAGES.append(
    inventory.StageDef(
        "deep review", "analysis.deepen", ResourceClass.CPU, after=("dispositions",), level=3
    )
)
inventory.PROJECT_STAGES.append(SUMMARIES_STAGE)
