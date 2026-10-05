"""Mosaics (ARCHITECTURE.md §8 stage 10): labelled contact sheets for the vision model.

Per asset, segments are laid out in time order on sheets of ``cols × rows`` tiles (Balanced:
4 × 4, ANALYSIS_MODES.md). Each segment gets up to ``PER_SEGMENT`` tiles spread over its
kept samples (usable range first) and is never split across sheets, so the model sees each
moment's continuity in one image. Every tile carries a burned-in label
``T07 · ast_0123 · 00:02:14.3`` and the ``mosaic_tile`` rows plus a JSON sidecar map the
label back to the sample and its source ticks: the model cites ``T07``, code resolves it.

Sheet size follows the vision provider's effective image size (``AdapterLimits``), so no
pixels are sent that the provider would discard.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from mosaic.ai.registry import limits_for, task_choice
from mosaic.core.keys import artifact_key
from mosaic.core.time import parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import SkipTask, task
from mosaic.library import segments as _segments  # noqa: F401 - registers "segments" first
from mosaic.library.purge import purge_mosaics
from mosaic.media import inventory
from mosaic.storage import provenance
from mosaic.storage.models_project import Asset, Mosaic, MosaicTile, SampleFrame, Segment

MOSAICS_VERSION = "mosaics/1"
GRID = {"balanced": (4, 4)}  # tiles per sheet by analysis mode (ANALYSIS_MODES.md)
PER_SEGMENT = 4
MAX_TILE_WIDTH = 640  # sample thumbnails are 640 px wide; larger tiles add nothing
GAP = 4
BACKGROUND = (20, 20, 20)
JPEG_QUALITY = 85


@dataclass(frozen=True)
class Geometry:
    cols: int
    rows: int
    tile_width: int
    tile_height: int

    @property
    def capacity(self) -> int:
        return self.cols * self.rows

    def size(self, used_rows: int) -> tuple[int, int]:
        return (
            self.cols * self.tile_width + (self.cols - 1) * GAP,
            used_rows * self.tile_height + (used_rows - 1) * GAP,
        )

    def origin(self, slot: int) -> tuple[int, int]:
        r, c = divmod(slot, self.cols)
        return c * (self.tile_width + GAP), r * (self.tile_height + GAP)


def geometry(mode: str, max_image_px: int) -> Geometry:
    cols, rows = GRID[mode]
    width = min(MAX_TILE_WIDTH, (max_image_px - (cols - 1) * GAP) // cols) // 2 * 2
    height = round(width * 9 / 16) // 2 * 2
    if (height + GAP) * rows - GAP > max_image_px:
        height = ((max_image_px - (rows - 1) * GAP) // rows) // 2 * 2
    return Geometry(cols, rows, width, height)


def spread(n: int, k: int) -> list[int]:
    """``min(n, k)`` indexes spread evenly over ``range(n)``, first and last included."""
    if n <= k:
        return list(range(n))
    if k == 1:
        return [(n - 1) // 2]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def pack(counts: list[int], capacity: int) -> list[list[int]]:
    """Group consecutive items (tile counts) onto sheets without splitting an item."""
    sheets: list[list[int]] = []
    used = capacity
    for i, n in enumerate(counts):
        if n > capacity:
            raise ValueError(f"item {i} needs {n} tiles, a sheet holds {capacity}")
        if used + n > capacity:
            sheets.append([])
            used = 0
        sheets[-1].append(i)
        used += n
    return sheets


def label_time(ticks: int, tb: str) -> str:
    """``hh:mm:ss.t`` of a logical asset position, for the burned-in label (display only)."""
    seconds = Fraction(ticks) * parse_rational(tb)
    tenths = math.floor(max(seconds, Fraction(0)) * 10)
    total, t = divmod(tenths, 10)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{t}"


def tile_label(tile: int, asset_id: int, ticks: int, tb: str) -> str:
    return f"T{tile:02d} · ast_{asset_id:04d} · {label_time(ticks, tb)}"


def choose_samples(
    segment: Segment, samples: list[SampleFrame], per_segment: int
) -> list[SampleFrame]:
    """Up to ``per_segment`` kept samples spread over the usable range (else the whole
    segment); a segment without one gets the nearest kept sample of its shot."""
    usable = [
        sm for sm in samples if segment.usable_start_ticks <= sm.ticks < segment.usable_end_ticks
    ]
    inside = usable or [sm for sm in samples if segment.start_ticks <= sm.ticks < segment.end_ticks]
    if inside:
        return [inside[i] for i in spread(len(inside), per_segment)]
    same_shot = [sm for sm in samples if sm.shot_id == segment.shot_id] or samples
    if not same_shot:
        return []
    mid = (segment.start_ticks + segment.end_ticks) // 2
    return [min(same_shot, key=lambda sm: (abs(sm.ticks - mid), sm.id))]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)  # Pillow's bundled OFL font; no runtime fetch


def render_sheet(geo: Geometry, tiles: list[tuple[bytes, str]], used_rows: int) -> bytes:
    """A JPEG contact sheet; ``tiles`` are ``(jpeg bytes, label)`` in slot order."""
    sheet = Image.new("RGB", geo.size(used_rows), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = _font(max(11, geo.tile_height // 13))
    pad = max(2, geo.tile_height // 60)
    for slot, (jpeg, label) in enumerate(tiles):
        x, y = geo.origin(slot)
        with Image.open(io.BytesIO(jpeg)) as im:
            frame = im.convert("RGB")
        frame.thumbnail((geo.tile_width, geo.tile_height), Image.Resampling.LANCZOS)
        sheet.paste(
            frame,
            (x + (geo.tile_width - frame.width) // 2, y + (geo.tile_height - frame.height) // 2),
        )
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        box_h = bottom - top + 2 * pad
        by = y + geo.tile_height - box_h
        draw.rectangle((x, by, x + right - left + 2 * pad, y + geo.tile_height - 1), fill=(0, 0, 0))
        draw.text((x + pad - left, by + pad - top), label, font=font, fill=(255, 255, 255))
    buf = io.BytesIO()
    sheet.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


# ------------------------------------------------------------------------ task


def _mode(ctx: TaskContext) -> str:
    job = ctx.store.job(ctx.task.job_id)
    mode = str((job.params if job else {}).get("mode", "balanced"))
    return mode if mode in GRID else "balanced"


def _geometry(ctx: TaskContext) -> Geometry:
    return geometry(_mode(ctx), limits_for(task_choice(ctx, "vision")).max_image_px)


def _inputs(ctx: TaskContext, asset_id: int) -> tuple[list[Segment], list[SampleFrame]]:
    with ctx.project.db.session() as s:
        segments = list(
            s.scalars(
                select(Segment).where(Segment.asset_id == asset_id).order_by(Segment.start_ticks)
            )
        )
        samples = list(
            s.scalars(
                select(SampleFrame)
                .where(
                    SampleFrame.asset_id == asset_id,
                    SampleFrame.kept.is_(True),
                    SampleFrame.image_key.is_not(None),
                )
                .order_by(SampleFrame.ticks, SampleFrame.id)
            )
        )
    return segments, samples


def _key(
    ctx: TaskContext, geo: Geometry, segments: list[Segment], samples: list[SampleFrame]
) -> str:
    return artifact_key(
        "mosaics",
        project_id=ctx.project.id,
        inputs={
            "asset": ctx.params["asset_id"],
            # Provenance ids are never reused, unlike SQLite row ids after a purge.
            "segments": [
                [
                    g.id,
                    g.provenance_id,
                    g.start_ticks,
                    g.end_ticks,
                    g.usable_start_ticks,
                    g.usable_end_ticks,
                ]
                for g in segments
            ],
            "samples": [
                [sm.id, sm.provenance_id, sm.ticks, sm.shot_id, sm.image_key] for sm in samples
            ],
        },
        config={
            "grid": [geo.cols, geo.rows],
            "tile": [geo.tile_width, geo.tile_height],
            "per_segment": PER_SEGMENT,
        },
        version=MOSAICS_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    """The artifact exists *and* the rows are present (a segments purge removes them)."""
    asset_id = ctx.params["asset_id"]
    segments, samples = _inputs(ctx, asset_id)
    if not ctx.project.artifacts.exists("mosaics", _key(ctx, _geometry(ctx), segments, samples)):
        return False
    if not segments:
        return True
    with ctx.project.db.session() as s:
        return s.scalar(select(Mosaic.id).where(Mosaic.asset_id == asset_id).limit(1)) is not None


@task("library.mosaics", is_done=_is_done)
def mosaics_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    geo = _geometry(ctx)
    segments, samples = _inputs(ctx, asset_id)
    if not segments:
        raise SkipTask("no segments")
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        assert asset.tb is not None
        tb = asset.tb
    key = _key(ctx, geo, segments, samples)
    chosen = [choose_samples(g, samples, PER_SEGMENT) for g in segments]
    covered = [i for i, c in enumerate(chosen) if c]
    sheets = pack([len(chosen[i]) for i in covered], geo.capacity)

    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="mosaics", algorithm_version=MOSAICS_VERSION, input_keys=[key]
            ),
        )
    artifacts = ctx.project.artifacts
    built: list[tuple[str, list[tuple[int, SampleFrame, Segment]]]] = []
    for n, sheet in enumerate(sheets):
        ctx.check_cancelled()
        slots = [(sm, segments[covered[i]]) for i in sheet for sm in chosen[covered[i]]]
        tiles = []
        layout = []
        for slot, (sm, seg) in enumerate(slots):
            assert sm.image_key is not None
            label = tile_label(slot + 1, asset_id, sm.ticks, tb)
            tiles.append((artifacts.get_bytes("frame", sm.image_key), label))
            layout.append((slot + 1, sm, seg))
        image_key = f"mosaic-{key[-24:]}-{n:03d}"
        artifacts.put_bytes(
            "mosaic",
            image_key,
            render_sheet(geo, tiles, math.ceil(len(slots) / geo.cols)),
            provenance_id=prov,
            ext=".jpg",
        )
        artifacts.put_json(
            "mosaic",
            f"{image_key}-tiles",
            {
                "asset_id": asset_id,
                "tb": tb,
                "tiles": [
                    {
                        "tile": f"T{t:02d}",
                        "sample_id": sm.id,
                        "segment_id": seg.id,
                        "time": {"ticks": sm.ticks, "tb": tb},
                    }
                    for t, sm, seg in layout
                ],
            },
            provenance_id=prov,
        )
        built.append((image_key, layout))

    with ctx.write() as s:
        purge_mosaics(s, asset_id)
        for n, (image_key, layout) in enumerate(built):
            row = Mosaic(
                asset_id=asset_id,
                index=n,
                image_key=image_key,
                cols=geo.cols,
                rows=geo.rows,
                tile_width=geo.tile_width,
                tile_height=geo.tile_height,
                provenance_id=prov,
            )
            s.add(row)
            s.flush()
            for t, sm, seg in layout:
                s.add(
                    MosaicTile(
                        mosaic_id=row.id, tile=t, sample_id=sm.id, segment_id=seg.id, ticks=sm.ticks
                    )
                )
    uncovered = len(segments) - len(covered)
    artifacts.put_json(
        "mosaics", key, {"mosaics": len(built), "uncovered": uncovered}, provenance_id=prov
    )
    return {"mosaics": len(built), "segments": len(covered), "uncovered": uncovered}


inventory.ASSET_STAGES.append(
    inventory.StageDef("mosaics", "library.mosaics", ResourceClass.CPU, after=("segments",))
)
