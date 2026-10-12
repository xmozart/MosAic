"""``library.focus``: each segment's subject position (ADR 0076), an L1 stage with no AI.

For every segment of an asset, the saliency of a few of its kept sample frames (those in
its usable range, evenly spread; a photo's one sample) gives one focus point in
thousandths of the frame, stored on the segment. Edits carry it into their events, so a
crop to another shape centres on the subject and a still's push-in ends on it. Keyed by
the asset's segments and samples: re-segmenting or re-sampling recomputes it.
"""

from __future__ import annotations

import io
from bisect import bisect_left, bisect_right
from typing import Any

from PIL import Image
from sqlalchemy import select

from mosaic.core.keys import artifact_key
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import task
from mosaic.library import photo_segment as _photo_segment  # noqa: F401 - registers first
from mosaic.library import segments as _segments  # noqa: F401 - registers first
from mosaic.media import inventory
from mosaic.media.saliency import MAP_WIDTH, focus_point
from mosaic.storage import provenance
from mosaic.storage.models_project import SampleFrame, Segment

FOCUS_VERSION = "focus/1"
FRAMES_PER_SEGMENT = 4


def _inputs(ctx: TaskContext) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    asset_id = ctx.params["asset_id"]
    with ctx.project.db.session() as s:
        segs = [
            tuple(r)
            for r in s.execute(
                select(
                    Segment.id,
                    Segment.provenance_id,
                    Segment.start_ticks,
                    Segment.end_ticks,
                    Segment.usable_start_ticks,
                    Segment.usable_end_ticks,
                )
                .where(Segment.asset_id == asset_id)
                .order_by(Segment.id)
            )
        ]
        samples = [
            tuple(r)
            for r in s.execute(
                select(
                    SampleFrame.id,
                    SampleFrame.provenance_id,
                    SampleFrame.ticks,
                    SampleFrame.image_key,
                )
                .where(
                    SampleFrame.asset_id == asset_id,
                    SampleFrame.kept.is_(True),
                    SampleFrame.image_key.is_not(None),
                )
                .order_by(SampleFrame.ticks, SampleFrame.id)
            )
        ]
    return segs, samples


def _key(ctx: TaskContext, segs: list[tuple[Any, ...]], samples: list[tuple[Any, ...]]) -> str:
    return artifact_key(
        "focus",
        project_id=ctx.project.id,
        inputs={
            "asset": ctx.params["asset_id"],
            "segments": [list(r) for r in segs],
            "samples": [[sid, prov] for sid, prov, _, _ in samples],
        },
        version=FOCUS_VERSION,
    )


def frames_for(
    a: int, b: int, samples: list[tuple[Any, ...]], n: int = FRAMES_PER_SEGMENT
) -> list[str]:
    """Up to ``n`` image keys of samples in [a, b) (the one at ``a`` for a one-frame
    segment), evenly spread."""
    ticks = [t for _, _, t, _ in samples]  # sorted by ticks (``_inputs``)
    lo = bisect_left(ticks, a)
    hi = bisect_right(ticks, a) if a == b else bisect_left(ticks, b)
    inside = [key for _, _, _, key in samples[lo:hi]]
    if len(inside) <= n:
        return inside
    step = len(inside) / n
    return [inside[int(i * step)] for i in range(n)]


def _read(ctx: TaskContext, image_key: str) -> Image.Image | None:
    """A sample frame, grey and decoded small (JPEG's own downscale); None when it is
    missing or unreadable: focus is an enrichment with a centre fallback (invariant 14)."""
    try:
        img = Image.open(io.BytesIO(ctx.project.artifacts.get_bytes("frame", image_key)))
        img.draft("L", (MAP_WIDTH * 2, MAP_WIDTH * 2))
        return img.convert("L")
    except (OSError, ValueError):
        return None


def _is_done(ctx: TaskContext) -> bool:
    segs, samples = _inputs(ctx)
    return ctx.project.artifacts.exists("focus", _key(ctx, segs, samples))


@task("library.focus", is_done=_is_done)
def focus_task(ctx: TaskContext) -> dict[str, Any]:
    segs, samples = _inputs(ctx)
    key = _key(ctx, segs, samples)
    found: dict[int, tuple[int, int] | None] = {}
    for sid, _, start, end, us, ue in segs:
        a, b = (us, ue) if ue > us else (start, end)
        images = []
        for image_key in frames_for(a, b, samples):
            img = _read(ctx, image_key)
            if img is not None:
                images.append(img)
        found[sid] = focus_point(images)  # no readable frame: None (the centre)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="focus", algorithm_version=FOCUS_VERSION, input_keys=[key]
            ),
        )
        for sid, point in found.items():
            seg = s.get(Segment, sid)
            if seg is not None:
                seg.focus_x, seg.focus_y = point if point else (None, None)
    ctx.project.artifacts.put_json(
        "focus",
        key,
        {"segments": len(found), "found": sum(1 for p in found.values() if p)},
        provenance_id=prov,
    )
    return {"segments": len(found)}


inventory.ASSET_STAGES.append(
    inventory.StageDef(
        "focus",
        "library.focus",
        ResourceClass.CPU,
        after=("segments", "photo_segment"),
        kinds=("video", "photo"),
    )
)
