"""Sample embeddings per asset (ARCHITECTURE.md §8 stages 5 and 9).

Kept samples are embedded with local SigLIP; a sample nearly identical to the previous kept
sample of the same shot (cosine similarity ≥ ``DEDUPE_SIM``) is then marked a duplicate,
completing the "pHash and embedding dedupe" of the samples stage. Scene-change samples are
always kept.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy import delete, select

from mosaic.ai.registry import task_embedder
from mosaic.core.keys import artifact_key
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import task
from mosaic.media import inventory
from mosaic.storage import provenance, sqlite_vec_index
from mosaic.storage.models_project import Embedding, SampleFrame

EMBED_VERSION = "embed/2"
DEDUPE_SIM = 0.97
BATCH = 16


def dedupe_by_embedding(
    samples: list[tuple[int, int, str, str | None]],
    vectors: dict[int, np.ndarray],
    threshold: float,
) -> dict[int, int]:
    """``{duplicate sample: earlier kept sample}`` within each shot.

    ``samples`` are ``(id, shot, reason, dup_reason)`` in time order. Samples dropped by
    pHash stay dropped and are never a reference; earlier embedding drops are recomputed;
    scene-change samples are always kept."""
    dups: dict[int, int] = {}
    last: dict[int, int] = {}
    for sid, shot, reason, dup_reason in samples:
        if dup_reason == "phash":
            continue
        prev = last.get(shot)
        if (
            reason != "scene"
            and prev is not None
            and float(vectors[sid] @ vectors[prev]) >= threshold
        ):
            dups[sid] = prev
            continue
        last[shot] = sid
    return dups


def _samples(ctx: TaskContext, asset_id: int) -> list[SampleFrame]:
    with ctx.project.db.session() as s:
        return list(
            s.scalars(
                select(SampleFrame)
                .where(SampleFrame.asset_id == asset_id, SampleFrame.image_key.is_not(None))
                .order_by(SampleFrame.ticks, SampleFrame.id)
            )
        )


def _key(ctx: TaskContext, samples: list[SampleFrame]) -> str:
    return artifact_key(
        "embed",
        project_id=ctx.project.id,
        inputs={"asset": ctx.params["asset_id"], "images": [sm.image_key for sm in samples]},
        config={"model": task_embedder(ctx).model, "dedupe": DEDUPE_SIM},
        version=EMBED_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    samples = _samples(ctx, ctx.params["asset_id"])
    return ctx.project.artifacts.exists("embed", _key(ctx, samples))


@task("library.embed", is_done=_is_done)
def embed_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    samples = _samples(ctx, asset_id)
    key = _key(ctx, samples)
    embedder = task_embedder(ctx)
    vectors: dict[int, np.ndarray] = {}
    for i in range(0, len(samples), BATCH):
        ctx.check_cancelled()
        batch = samples[i : i + BATCH]
        images = [
            Image.open(io.BytesIO(ctx.project.artifacts.get_bytes("frame", sm.image_key)))
            for sm in batch
            if sm.image_key
        ]
        for sm, vec in zip(batch, embedder.embed(images), strict=True):
            vectors[sm.id] = vec

    dups = dedupe_by_embedding(
        [(sm.id, sm.shot_id, sm.reason, sm.dup_reason) for sm in samples], vectors, DEDUPE_SIM
    )

    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="embed",
                algorithm_version=EMBED_VERSION,
                model=embedder.model,
                provider="local-onnx",
                input_keys=[key],
            ),
        )
        index = sqlite_vec_index.ensure_index(s, embedder.model, embedder.dim, "sample")
        old = list(
            s.scalars(
                select(Embedding.id).where(
                    Embedding.owner_kind == "sample",
                    Embedding.owner_id.in_([sm.id for sm in samples]),
                    Embedding.model == embedder.model,
                )
            )
        )
        sqlite_vec_index.delete(s, index, old)
        s.execute(delete(Embedding).where(Embedding.id.in_(old)))
        for sm in samples:
            row = Embedding(
                owner_kind="sample",
                owner_id=sm.id,
                model=embedder.model,
                dim=embedder.dim,
                vector=vectors[sm.id].astype(np.float32).tobytes(),
                provenance_id=prov,
            )
            s.add(row)
            s.flush()
            sqlite_vec_index.upsert(s, index, row.id, vectors[sm.id])
            live = s.get(SampleFrame, sm.id)
            assert live is not None
            if live.dup_reason == "embedding":  # earlier run's decision: recompute it
                live.kept, live.dup_of, live.dup_reason = True, None, None
            if sm.id in dups:
                live.kept, live.dup_of, live.dup_reason = False, dups[sm.id], "embedding"
    ctx.project.artifacts.put_json(
        "embed", key, {"samples": len(samples), "deduped": len(dups)}, provenance_id=prov
    )
    return {"samples": len(samples), "deduped": len(dups)}


inventory.ASSET_STAGES.append(
    inventory.StageDef("embed", "library.embed", ResourceClass.CPU, after=("visual",))
)
