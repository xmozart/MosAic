"""Similarity groups and segment quality (ARCHITECTURE.md §8 stage 12; M0: embedding only).

Leader clustering on pooled SigLIP segment embeddings (ADR 0011): segments are visited best
quality first; each joins the group whose *seed* is nearest within ``MAX_DISTANCE`` (cosine,
found through the sqlite-vec segment index) or becomes a new seed. Comparing with seeds, not
with any member, prevents single-linkage chaining across a trip. Groups of two or more are
stored; the seed (best quality) is the recommended pick. The threshold is calibrated on the
real corpus in M0 step 12.

Memory stays bounded: quality is computed per asset, and vectors are read one at a time
(invariant 13).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mosaic.ai.registry import task_embedder
from mosaic.core.keys import artifact_key
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import task
from mosaic.library.quality import shake_metric_name
from mosaic.media import inventory
from mosaic.storage import provenance, sqlite_vec_index
from mosaic.storage.models_project import (
    Asset,
    Embedding,
    SampleFrame,
    Segment,
    SimilarityGroup,
    TechMetric,
)

SIMILARITY_VERSION = "similarity/2"
MAX_DISTANCE = 0.06  # cosine distance (similarity ≥ 0.94)
NEIGHBOURS = 12


def leader_groups(
    order: list[int],
    neighbours: Callable[[int], list[tuple[float, int]]],
    max_distance: float,
) -> list[tuple[int, list[int]]]:
    """Leader clustering. ``order`` is best first; ``neighbours(item)`` gives
    ``(distance, other)``. Returns ``(seed, members)`` for groups of two or more."""
    seed_of: dict[int, int] = {}
    for item in order:
        seeds = sorted(
            (d, o)
            for d, o in neighbours(item)
            if o != item and d <= max_distance and seed_of.get(o) == o
        )
        seed_of[item] = seeds[0][1] if seeds else item
    members: dict[int, list[int]] = {}
    for item, seed in seed_of.items():
        members.setdefault(seed, []).append(item)
    return [(seed, sorted(m)) for seed, m in members.items() if len(m) >= 2]


def _percentiles(
    metrics: list[TechMetric], sample_ticks: dict[int, int], name: str, a: int, b: int
) -> list[float]:
    """Percentiles of ``name`` for samples inside ``[a, b)`` or ranges overlapping it."""
    out = []
    for m in metrics:
        if m.name != name or m.percentile is None:
            continue
        if m.sample_id is not None:
            t = sample_ticks.get(m.sample_id, m.start_ticks)
            if a <= t < b:
                out.append(m.percentile)
        elif m.start_ticks < b and m.end_ticks > a:
            out.append(m.percentile)
    return out


def asset_quality(session: Session, asset_id: int) -> dict[int, float]:
    """Quality per segment of one asset from project-normalized percentiles: sharpness up,
    shake and clipping down. Only the ordering matters."""
    segs = list(
        session.execute(
            select(
                Segment.id,
                Segment.usable_start_ticks,
                Segment.usable_end_ticks,
                Segment.start_ticks,
                Segment.end_ticks,
            ).where(Segment.asset_id == asset_id)
        )
    )
    metrics = list(session.scalars(select(TechMetric).where(TechMetric.asset_id == asset_id)))
    sample_ticks = {
        r[0]: r[1]
        for r in session.execute(
            select(SampleFrame.id, SampleFrame.ticks).where(SampleFrame.asset_id == asset_id)
        )
    }
    shake_name = shake_metric_name({m.name for m in metrics})
    scores: dict[int, float] = {}
    for sid, ua, ub, a, b in segs:
        if ub <= ua:
            ua, ub = a, b
        sharp = _percentiles(metrics, sample_ticks, "sharpness", ua, ub)
        shake = _percentiles(metrics, sample_ticks, shake_name, ua, ub)
        clip = _percentiles(metrics, sample_ticks, "clip_high", ua, ub) + _percentiles(
            metrics, sample_ticks, "clip_low", ua, ub
        )
        scores[sid] = (
            (float(np.mean(sharp)) if sharp else 0.5)
            - (float(np.mean(shake)) if shake else 0.5)
            - 0.5 * (float(np.mean(clip)) if clip else 0.0)
        )
    return scores


def _key(ctx: TaskContext) -> str:
    """Digest of every input: segment embeddings (and their provenance) and the metric
    provenance that percentiles come from, streamed (no project-sized lists)."""
    h = hashlib.sha256()
    with ctx.project.db.session() as s:
        for row in s.execute(
            select(Embedding.owner_id, Embedding.provenance_id)
            .where(Embedding.owner_kind == "segment", Embedding.model == task_embedder(ctx).model)
            .order_by(Embedding.owner_id)
        ):
            h.update(f"{row[0]}:{row[1]};".encode())
        for pid in s.scalars(
            select(TechMetric.provenance_id).distinct().order_by(TechMetric.provenance_id)
        ):
            h.update(f"m{pid};".encode())
    return artifact_key(
        "similarity",
        project_id=ctx.project.id,
        inputs=h.hexdigest(),
        config={
            "model": task_embedder(ctx).model,
            "max_distance": MAX_DISTANCE,
            "neighbours": NEIGHBOURS,
        },
        version=SIMILARITY_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("similarity", _key(ctx))


@task("library.similarity", is_done=_is_done)
def similarity_task(ctx: TaskContext) -> dict[str, Any]:
    emb = task_embedder(ctx)
    model = emb.model
    key = _key(ctx)
    quality: dict[int, float] = {}
    with ctx.project.db.session() as s:
        for asset_id in s.scalars(select(Asset.id).where(Asset.kind == "video")):
            quality.update(asset_quality(s, asset_id))
        index = sqlite_vec_index.index_name(model, emb.dim, "segment")
        emb_of = {
            r[0]: r[1]
            for r in s.execute(
                select(Embedding.owner_id, Embedding.id).where(
                    Embedding.owner_kind == "segment", Embedding.model == model
                )
            )
        }
        seg_of = {e: sid for sid, e in emb_of.items()}
        order = sorted(emb_of, key=lambda sid: (-quality.get(sid, 0.0), sid))

        def neighbours(sid: int) -> list[tuple[float, int]]:
            blob = s.scalar(select(Embedding.vector).where(Embedding.id == emb_of[sid]))
            assert blob is not None
            vec = np.frombuffer(blob, dtype=np.float32)
            hits = sqlite_vec_index.knn(s, index, vec, NEIGHBOURS)
            return [(dist, seg_of[e]) for e, dist in hits if e in seg_of]

        groups = leader_groups(order, neighbours, MAX_DISTANCE)

    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="similarity",
                algorithm_version=SIMILARITY_VERSION,
                model=model,
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
        s.execute(update(Segment).values(similarity_group_id=None, group_best=False))
        s.query(SimilarityGroup).delete()
        for seg_id, q in quality.items():
            s.execute(update(Segment).where(Segment.id == seg_id).values(quality=q))
        for best, members in groups:
            g = SimilarityGroup(
                method="embedding", size=len(members), best_segment_id=best, provenance_id=prov
            )
            s.add(g)
            s.flush()
            s.execute(
                update(Segment).where(Segment.id.in_(members)).values(similarity_group_id=g.id)
            )
            s.execute(update(Segment).where(Segment.id == best).values(group_best=True))
    ctx.project.artifacts.put_json("similarity", key, {"groups": len(groups)}, provenance_id=prov)
    return {"groups": len(groups), "segments": len(quality)}


inventory.PROJECT_STAGES.append(
    inventory.StageDef("similarity", "library.similarity", ResourceClass.CPU)
)
