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
from mosaic.jobs.registry import SkipTask, task
from mosaic.library.context import load as load_context
from mosaic.library.dispositions import effective
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


def plan_deepen(
    session: Session, day: int | None = None, segment_ids: list[int] | None = None
) -> tuple[dict[int, list[int]], list[int]]:
    """(asset id → L3 candidates in scope, requested ids that are not candidates). Days
    are numbered exactly as the editor numbers them (``retrieval.trip_day``)."""
    assets = list(session.scalars(select(Asset).where(Asset.kind == "video").order_by(Asset.id)))
    first = min(capture_dates(assets).values(), default=None)
    wanted = set(segment_ids or [])
    plan: dict[int, list[int]] = {}
    found: set[int] = set()
    for a in assets:
        ids = candidate_ids(session, a.id)
        if wanted:
            ids = [i for i in ids if i in wanted]
        if day is not None and a.tb is not None:
            segs = {g.id: g for g in session.scalars(select(Segment).where(Segment.id.in_(ids)))}
            rate = parse_rational(a.tb)
            ids = [
                i
                for i in ids
                if trip_day(a.capture_time, Fraction(segs[i].start_ticks) * rate, first) == day
            ]
        found |= set(ids)
        if ids:
            plan[a.id] = ids
    return plan, sorted(wanted - found)


def submit_deepen(
    executor: Any,
    principal: Any,
    project: Any,
    *,
    day: int | None = None,
    segment_ids: list[int] | None = None,
    cost_limit_usd: float | None = None,
) -> tuple[int | None, int, list[int]]:
    """Start an L3 deepening job. Returns (job id, or None when nothing is in scope;
    candidate count; requested ids that are not candidates)."""
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
    from mosaic.media.pipeline import job_cost_limit

    with project.db.session() as s:
        plan, dropped = plan_deepen(s, day, segment_ids)
    count = sum(len(v) for v in plan.values())
    if not plan:
        return None, 0, dropped
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
    tasks.append(
        TaskSpec(
            kind="library.dispositions",
            stage="dispositions",
            resource_class=ResourceClass.CPU,
            label="dispositions",
            deps=list(range(len(tasks))),
        )
    )
    job = executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="deepen",
            params={"day": day, "segments": len(segment_ids or [])},
            cost_limit_usd=job_cost_limit(principal) if cost_limit_usd is None else cost_limit_usd,
            tasks=tasks,
        ),
    )
    return job, count, dropped
