"""A photo's single segment (ADR 0025): the whole picture, at tick 0, with its sample's
embedding as the segment embedding. Written after the embed stage so similarity, mosaics
and vision see photos exactly like one-frame clips."""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import select

from mosaic.ai.registry import task_embedder
from mosaic.core.keys import artifact_key
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, task
from mosaic.library import embed_task as _embed  # noqa: F401 - registers "embed" first
from mosaic.library.purge import purge_segments, reattach_user_dispositions
from mosaic.media import inventory
from mosaic.storage import provenance, sqlite_vec_index
from mosaic.storage.models_project import Embedding, SampleFrame, Segment, Shot

PHOTO_SEGMENT_VERSION = "photo-segment/1"


def _inputs(ctx: TaskContext) -> tuple[SampleFrame, Embedding | None]:
    asset_id = ctx.params["asset_id"]
    model = task_embedder(ctx).model
    with ctx.project.db.session() as s:
        sample = s.scalar(select(SampleFrame).where(SampleFrame.asset_id == asset_id).limit(1))
        if sample is None:
            raise PermanentError(f"photo asset {asset_id} has no sample")
        emb = s.scalar(
            select(Embedding).where(
                Embedding.owner_kind == "sample",
                Embedding.owner_id == sample.id,
                Embedding.model == model,
            )
        )
        s.expunge(sample)
        if emb is not None:
            s.expunge(emb)
    return sample, emb


def _key(ctx: TaskContext, sample: SampleFrame, emb: Embedding | None) -> str:
    return artifact_key(
        "segments",
        project_id=ctx.project.id,
        inputs={
            "asset": ctx.params["asset_id"],
            "sample": [sample.id, sample.provenance_id],
            "embedding": [emb.id, emb.provenance_id] if emb else None,
        },
        version=PHOTO_SEGMENT_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    sample, emb = _inputs(ctx)
    if not ctx.project.artifacts.exists("segments", _key(ctx, sample, emb)):
        return False
    with ctx.project.db.session() as s:
        return (
            s.scalar(select(Segment.id).where(Segment.asset_id == ctx.params["asset_id"]).limit(1))
            is not None
        )


@task("photo.segment", is_done=_is_done)
def photo_segment_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    sample, emb = _inputs(ctx)
    key = _key(ctx, sample, emb)
    embedder = task_embedder(ctx)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="segments", algorithm_version=PHOTO_SEGMENT_VERSION, input_keys=[key]
            ),
        )
        purge_segments(s, asset_id)
        shot_id = s.scalar(select(Shot.id).where(Shot.asset_id == asset_id).limit(1))
        assert shot_id is not None
        seg = Segment(
            asset_id=asset_id,
            shot_id=shot_id,
            index=0,
            start_ticks=0,
            end_ticks=0,
            usable_start_ticks=0,
            usable_end_ticks=0,
            has_speech=False,
            provenance_id=prov,
        )
        s.add(seg)
        s.flush()
        if emb is not None:
            vec = np.frombuffer(emb.vector, dtype=np.float32)
            # A separate kind and index: photos never take video segments' nearest-
            # neighbour slots in similarity (ADR 0025).
            index = sqlite_vec_index.ensure_index(s, embedder.model, embedder.dim, "photo_segment")
            row = Embedding(
                owner_kind="photo_segment",
                owner_id=seg.id,
                model=embedder.model,
                dim=embedder.dim,
                vector=vec.tobytes(),
                provenance_id=prov,
            )
            s.add(row)
            s.flush()
            sqlite_vec_index.upsert(s, index, row.id, vec)
        reattach_user_dispositions(s, asset_id)
    ctx.project.artifacts.put_json("segments", key, {"segments": 1}, provenance_id=prov)
    return {"segments": 1}


inventory.ASSET_STAGES.append(
    inventory.StageDef(
        "photo_segment", "photo.segment", ResourceClass.CPU, after=("embed",), kinds=("photo",)
    )
)
