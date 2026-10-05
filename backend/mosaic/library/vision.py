"""Vision (ARCHITECTURE.md §8 stage 11): one structured observation per segment.

The mosaic is the transport format, the segment is the unit. Each sheet is sent once with
the ``vision`` prompt through ``AIClient`` (cached by request, budgeted, validated); the
answer must cover every segment on the sheet exactly once and cite a ``best_tile`` from the
segment's own tiles, which code resolves to the sample and its source ticks.

When the vision provider cannot be used (no key, ``ai.local_only`` on), the stage is
skipped with the reason and dispositions fall back to the deterministic rules (ADR 0013).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from PIL import Image
from sqlalchemy import delete, select

from mosaic.ai.client import AIClient
from mosaic.ai.prompts.vision.schema_v1 import Output
from mosaic.ai.registry import task_check_ready, task_choice
from mosaic.ai.types import ImageInput
from mosaic.core.keys import artifact_key
from mosaic.core.time import format_display, parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import SkipTask, task
from mosaic.library.mosaics import label_time
from mosaic.media import inventory
from mosaic.storage import provenance
from mosaic.storage.config import NotConfiguredError
from mosaic.storage.models_project import Asset, Mosaic, MosaicTile, Segment, VisualObservation

PROMPT = ("vision", 1)
VISION_VERSION = "vision-task/1"
MAX_TOKENS = 6000


@dataclass(frozen=True)
class SheetSegment:
    ref: str  # S1…
    segment_id: int
    tiles: list[tuple[int, int, int]]  # (tile, sample_id, ticks)
    start_ticks: int
    end_ticks: int
    has_speech: bool


def sheet_segments(tiles: list[MosaicTile], segments: dict[int, Segment]) -> list[SheetSegment]:
    """Segments of one sheet in tile order, with their references ``S1``…"""
    order: list[int] = []
    by_seg: dict[int, list[tuple[int, int, int]]] = {}
    for t in sorted(tiles, key=lambda t: t.tile):
        if t.segment_id not in by_seg:
            order.append(t.segment_id)
            by_seg[t.segment_id] = []
        by_seg[t.segment_id].append((t.tile, t.sample_id, t.ticks))
    out = []
    for i, sid in enumerate(order, 1):
        seg = segments[sid]
        out.append(
            SheetSegment(f"S{i}", sid, by_seg[sid], seg.start_ticks, seg.end_ticks, seg.has_speech)
        )
    return out


def segment_lines(items: list[SheetSegment], tb: str) -> str:
    lines = []
    rate = parse_rational(tb)
    for it in items:
        first, last = it.tiles[0][0], it.tiles[-1][0]
        tiles = f"T{first:02d}" if first == last else f"T{first:02d}–T{last:02d}"
        dur = format_display(Fraction(it.end_ticks - it.start_ticks) * rate)
        speech = "speech" if it.has_speech else "no speech"
        lines.append(
            f"{it.ref}: tiles {tiles}, {label_time(it.start_ticks, tb)}–"
            f"{label_time(it.end_ticks, tb)} ({dur}), {speech}"
        )
    return "\n".join(lines)


def check_answer(answer: Output, items: list[SheetSegment]) -> list[str]:
    """Rules the schema cannot express: every segment once, best tile its own."""
    errors = []
    tiles_of = {it.ref: {f"T{t:02d}" for t, _, _ in it.tiles} for it in items}
    seen: dict[str, int] = {}
    for obs in answer.segments:
        seen[obs.segment] = seen.get(obs.segment, 0) + 1
        if obs.segment not in tiles_of:
            errors.append(f"{obs.segment} is not a segment on this sheet")
        elif obs.best_tile not in tiles_of[obs.segment]:
            allowed = ", ".join(sorted(tiles_of[obs.segment]))
            errors.append(f"{obs.segment}: best_tile {obs.best_tile} is not one of {allowed}")
    for ref in tiles_of:
        if seen.get(ref, 0) == 0:
            errors.append(f"{ref} is missing; return one observation for it")
        elif seen[ref] > 1:
            errors.append(f"{ref} appears {seen[ref]} times; return exactly one observation")
    return errors


def observation_data(obs: Any, item: SheetSegment, tb: str) -> dict[str, Any]:
    data: dict[str, Any] = obs.model_dump(mode="json", exclude={"segment", "best_tile"})
    tile = int(obs.best_tile[1:])
    _, sample_id, ticks = next(t for t in item.tiles if t[0] == tile)
    data["best_frame"] = {
        "tile": obs.best_tile,
        "sample_id": sample_id,
        "time": {"ticks": ticks, "tb": tb},
    }
    return data


# ------------------------------------------------------------------------ task


def _mosaics(ctx: TaskContext, asset_id: int) -> list[Mosaic]:
    with ctx.project.db.session() as s:
        return list(
            s.scalars(select(Mosaic).where(Mosaic.asset_id == asset_id).order_by(Mosaic.index))
        )


def _key(ctx: TaskContext, mosaics: list[Mosaic]) -> str:
    choice = task_choice(ctx, "vision")
    return artifact_key(
        "vision",
        project_id=ctx.project.id,
        inputs={
            "asset": ctx.params["asset_id"],
            "mosaics": [[m.id, m.provenance_id, m.image_key] for m in mosaics],
        },
        config={"provider": choice.provider, "model": choice.model, "prompt": list(PROMPT)},
        version=VISION_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    """The artifact exists *and* every tiled segment has its observation row."""
    mosaics = _mosaics(ctx, ctx.params["asset_id"])
    if not mosaics or not ctx.project.artifacts.exists("vision", _key(ctx, mosaics)):
        return False
    ids = [m.id for m in mosaics]
    with ctx.project.db.session() as s:
        missing = s.scalar(
            select(MosaicTile.segment_id)
            .where(
                MosaicTile.mosaic_id.in_(ids),
                MosaicTile.segment_id.not_in(select(VisualObservation.segment_id)),
            )
            .limit(1)
        )
    return missing is None


@task("library.vision", is_done=_is_done)
def vision_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    mosaics = _mosaics(ctx, asset_id)
    if not mosaics:
        raise SkipTask("no mosaics")
    try:
        task_check_ready(ctx, "vision")
    except NotConfiguredError as exc:
        raise SkipTask(f"vision skipped: {exc}") from None
    key = _key(ctx, mosaics)
    choice = task_choice(ctx, "vision")
    client = AIClient(ctx)
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        assert asset.tb is not None
        tb = asset.tb
        camera = " ".join(x for x in (asset.camera_make, asset.camera_model) if x) or asset.profile
    cost = 0.0
    cached = 0
    observed = 0
    call_provenance: list[int] = []
    for mosaic in mosaics:
        ctx.check_cancelled()
        with ctx.project.db.session() as s:
            tiles = list(s.scalars(select(MosaicTile).where(MosaicTile.mosaic_id == mosaic.id)))
            segs = {
                g.id: g
                for g in s.scalars(
                    select(Segment).where(Segment.id.in_({t.segment_id for t in tiles}))
                )
            }
        items = sheet_segments(tiles, segs)
        jpeg = ctx.project.artifacts.get_bytes("mosaic", mosaic.image_key)
        with Image.open(io.BytesIO(jpeg)) as im:
            width, height = im.size
        context = {
            "asset": f"ast_{asset_id:04d}",
            "camera": camera,
            "tile_count": len(tiles),
            "segment_list": segment_lines(items, tb),
            "segments": [
                {"ref": it.ref, "tiles": [f"T{t:02d}" for t, _, _ in it.tiles]} for it in items
            ],
        }

        def validate(answer: Any, items: list[SheetSegment] = items) -> list[str]:
            return check_answer(answer, items)

        result = client.structured(
            "vision",
            *PROMPT,
            context,
            [ImageInput(jpeg, "image/jpeg", width, height)],
            max_tokens=MAX_TOKENS,
            validate=validate,
        )
        cost += result.cost_usd
        call_provenance.append(result.provenance_id)
        cached += int(result.cached)
        answer = result.data
        assert isinstance(answer, Output)
        by_ref = {it.ref: it for it in items}
        with ctx.write() as s:
            s.execute(
                delete(VisualObservation).where(
                    VisualObservation.segment_id.in_([it.segment_id for it in items])
                )
            )
            for obs in answer.segments:
                item = by_ref[obs.segment]
                s.add(
                    VisualObservation(
                        segment_id=item.segment_id,
                        mosaic_id=mosaic.id,
                        data=observation_data(obs, item, tb),
                        provenance_id=result.provenance_id,
                    )
                )
        observed += len(items)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="vision",
                algorithm_version=VISION_VERSION,
                prompt_version=f"{PROMPT[0]}/v{PROMPT[1]}",
                provider=choice.provider,
                model=choice.model,
                input_keys=[key, *(f"prov:{p}" for p in call_provenance)],
            ),  # costs stay on the per-call rows; this marks the stage complete
        )
    ctx.project.artifacts.put_json(
        "vision", key, {"mosaics": len(mosaics), "segments": observed}, provenance_id=prov
    )
    return {
        "mosaics": len(mosaics),
        "segments": observed,
        "cached": cached,
        "cost_usd": round(cost, 6),
    }


inventory.ASSET_STAGES.append(
    inventory.StageDef(
        "vision", "library.vision", ResourceClass.AI_API, after=("mosaics",), level=2
    )
)
