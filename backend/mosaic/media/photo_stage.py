"""Photo analysis stage (ARCHITECTURE.md §8 for stills; MEDIA_SUPPORT.md §3; ADR 0025).

A photo is one picture. This stage writes the same rows a video's visual stage writes, so
embeddings, mosaics, vision, similarity and dispositions treat it as a one-frame clip:

- a thumbnail sample (the frame vision sees);
- frame metrics, measured at proxy scale (short side 720) so percentiles compare with
  video frames;
- one shot at tick 0 of a ``1/1`` time base.

The segment follows in ``library.photo_segment`` once the sample has an embedding.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy import delete, select

from mosaic.core.keys import artifact_key
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.purge import purge_sample_derived
from mosaic.media import inventory, l1
from mosaic.media.photo import PhotoError, open_image
from mosaic.media.proxy import PROXY_SHORT_SIDE
from mosaic.media.visual import THUMB_WIDTH
from mosaic.storage import provenance, stage_state
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    MediaFile,
    SampleFrame,
    Shot,
    TechMetric,
)

PHOTO_VERSION = "photo/1"
METRICS = ("sharpness", "exposure_mean", "clip_low", "clip_high", "noise", "obstruction")


def _source(ctx: TaskContext, asset_id: int) -> tuple[str, str]:
    with ctx.project.db.session() as s:
        row = s.execute(
            select(MediaFile.rel_path, MediaFile.fingerprint)
            .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
            .where(AssetFile.asset_id == asset_id)
            .order_by(AssetFile.order)
            .limit(1)
        ).first()
    if row is None:
        raise PermanentError(f"asset {asset_id} has no picture file")
    return row[0], row[1]


def _key(ctx: TaskContext) -> str:
    _, fp = _source(ctx, ctx.params["asset_id"])
    return artifact_key(
        "photo",
        project_id=ctx.project.id,
        inputs={"file": fp, "asset": ctx.params["asset_id"]},
        config={"thumb": THUMB_WIDTH, "metrics_short_side": PROXY_SHORT_SIDE},
        version=PHOTO_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    key = _key(ctx)
    if not ctx.project.artifacts.exists("photo", key):
        return False
    with ctx.project.db.session() as s:
        return stage_state.is_current(s, ctx.params["asset_id"], "photo", key)


def _scaled(img: Image.Image, short_side: int) -> Image.Image:
    short = min(img.width, img.height)
    if short <= short_side:
        return img
    f = short_side / short
    return img.resize((round(img.width * f), round(img.height * f)), Image.Resampling.BILINEAR)


@task("photo.analyze", is_done=_is_done)
def photo_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    rel, _ = _source(ctx, asset_id)
    key = _key(ctx)
    try:
        img, _meta = open_image(ctx.project.root / rel, PROXY_SHORT_SIDE)
    except PhotoError as exc:
        raise PermanentError(f"{rel}: {exc}") from None
    rgb_img = img.convert("RGB")
    rgb = np.asarray(_scaled(rgb_img, PROXY_SHORT_SIDE), dtype=np.uint8)
    gray = l1.luma(rgb)
    metrics = l1.frame_metrics(gray)
    ph = l1.phash(gray)
    thumb = rgb_img
    if thumb.width > THUMB_WIDTH:
        thumb = thumb.resize(
            (THUMB_WIDTH, round(thumb.height * THUMB_WIDTH / thumb.width)),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=85)
    with ctx.write() as s:
        stage_state.mark(s, asset_id, "photo", "")  # rows are being replaced
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="photo",
                algorithm_version=PHOTO_VERSION,
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
    image_key = f"frame-{key[-24:]}-0"
    ctx.project.artifacts.put_bytes(
        "frame", image_key, buf.getvalue(), provenance_id=prov, ext=".jpg"
    )
    with ctx.write() as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        s.execute(delete(TechMetric).where(TechMetric.asset_id == asset_id))
        purge_sample_derived(s, asset_id)
        s.execute(delete(SampleFrame).where(SampleFrame.asset_id == asset_id))
        s.execute(delete(Shot).where(Shot.asset_id == asset_id))
        shot = Shot(
            asset_id=asset_id,
            index=0,
            start_ticks=0,
            end_ticks=0,
            method="photo",
            provenance_id=prov,
        )
        s.add(shot)
        s.flush()
        sample = SampleFrame(
            asset_id=asset_id,
            shot_id=shot.id,
            ticks=0,
            reason="photo",
            phash=f"{ph:016x}",
            kept=True,
            image_key=image_key,
            provenance_id=prov,
        )
        s.add(sample)
        s.flush()
        for name in METRICS:
            s.add(
                TechMetric(
                    asset_id=asset_id,
                    sample_id=sample.id,
                    start_ticks=0,
                    end_ticks=0,
                    name=name,
                    value=float(getattr(metrics, name)),
                    provenance_id=prov,
                )
            )
    ctx.project.artifacts.put_json(
        "photo", key, {"width": img.width, "height": img.height}, provenance_id=prov
    )
    with ctx.write() as s:
        stage_state.mark(s, asset_id, "photo", key)
    return {"width": img.width, "height": img.height}


inventory.ASSET_STAGES.append(
    inventory.StageDef("photo", "photo.analyze", ResourceClass.CPU, kinds=("photo",))
)
