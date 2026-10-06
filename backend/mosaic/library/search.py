"""Hybrid search (ARCHITECTURE.md §12, S12, ADR 0029).

- **Visual:** the query's SigLIP text embedding against every sample's image embedding
  (video samples and photos), nearest first. A segment ranks by its best sample.
- **Text:** FTS5 over vision and L3 descriptions, tags and transcripts.
- **Merge:** the two rankings are merged with reciprocal rank fusion, ``Σ 1 / (60 +
  rank)``. Each result says what matched: tags or a description for visual hits, a
  transcript or description snippet for text hits.

Modes: ``all`` (both), ``visual`` (embeddings, plus FTS over descriptions and tags) and
``speech`` (FTS over transcripts only). The index is rebuilt by a project stage whenever
its inputs change. Queries only read.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from mosaic.ai.registry import task_embedder
from mosaic.core.keys import artifact_key
from mosaic.core.modes import task_mode
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass, TaskSpec
from mosaic.jobs.registry import SkipTask, task
from mosaic.library.dispositions import effective
from mosaic.media import inventory
from mosaic.storage import provenance, sqlite_fts, sqlite_vec_index
from mosaic.storage.models_project import (
    Asset,
    DeepReview,
    Embedding,
    ProjectMeta,
    SampleFrame,
    Segment,
    TranscriptSegment,
    VisualObservation,
)

log = logging.getLogger(__name__)

SEARCH_VERSION = "search-index/1"
SUGGESTIONS = 12
SUGGESTIONS_KEY = "search_suggestions"
RRF_K = 60
VISUAL_CANDIDATES = 400  # sample neighbours fetched per query
MODES = ("all", "visual", "speech")


# --------------------------------------------------------------------- index


def _observations(s: Session, ids: list[int]) -> dict[int, dict[str, Any]]:
    obs = {
        o.segment_id: o.data
        for o in s.scalars(select(VisualObservation).where(VisualObservation.segment_id.in_(ids)))
    }
    obs |= {  # L3 supersedes L2
        r.segment_id: r.data
        for r in s.scalars(select(DeepReview).where(DeepReview.segment_id.in_(ids)))
    }
    return obs


def index_rows(s: Session) -> Any:
    """``(segment id, field, body)`` for every segment, asset by asset (bounded memory)."""
    for asset_id in s.scalars(select(Asset.id).where(Asset.status == "ok")):
        segs = list(
            s.execute(
                select(Segment.id, Segment.start_ticks, Segment.end_ticks).where(
                    Segment.asset_id == asset_id
                )
            )
        )
        if not segs:
            continue
        obs = _observations(s, [g[0] for g in segs])
        words = list(
            s.execute(
                select(
                    TranscriptSegment.start_ticks,
                    TranscriptSegment.end_ticks,
                    TranscriptSegment.text,
                )
                .where(TranscriptSegment.asset_id == asset_id)
                .order_by(TranscriptSegment.start_ticks)
            )
        )
        for sid, a, b in segs:
            o = obs.get(sid)
            if o:
                yield sid, "visual", str(o.get("description", ""))
                tags = [*o.get("subjects", []), *o.get("issues", [])]
                yield sid, "tags", " ".join(str(t).replace("_", " ") for t in tags)
            speech = " ".join(t for x, y, t in words if x < max(b, a + 1) and y > a)
            if speech:
                yield sid, "speech", speech


def _key(ctx: TaskContext) -> str:
    h = hashlib.sha256()
    with ctx.project.db.session() as s:
        for table in (VisualObservation, DeepReview):
            for row in s.execute(
                select(table.segment_id, table.provenance_id).order_by(table.segment_id)
            ):
                h.update(repr(tuple(row)).encode())
        for row in s.execute(
            select(TranscriptSegment.asset_id, TranscriptSegment.provenance_id)
            .distinct()
            .order_by(TranscriptSegment.asset_id)
        ):
            h.update(repr(tuple(row)).encode())
        for row in s.execute(select(Segment.id, Segment.provenance_id).order_by(Segment.id)):
            h.update(repr(tuple(row)).encode())
    return artifact_key(
        "search", project_id=ctx.project.id, inputs=h.hexdigest(), version=SEARCH_VERSION
    )


def _is_done(ctx: TaskContext) -> bool:
    """Done when the index matches its inputs *and* the text model is here: an offline
    run is retried, so visual search does not stay off."""
    if not ctx.project.artifacts.exists("search", _key(ctx)):
        return False
    try:
        emb = task_embedder(ctx)
    except Exception:
        return True  # no embedder configured: nothing to fetch
    has = getattr(emb, "has_text_model", None)
    return bool(has()) if has is not None else True


@task("library.search_index", is_done=_is_done)
def search_index_task(ctx: TaskContext) -> dict[str, Any]:
    if task_mode(ctx).l3 and not ctx.params.get("final"):
        raise SkipTask("the search index follows the deep review")  # as summaries do
    key = _key(ctx)
    # Fetch the SigLIP text tower here, in a job, so search requests never download.
    try:
        task_embedder(ctx).embed_text(["warm up"])
        visual = "ready"
    except Exception as exc:  # offline or no embedder: text search still works
        visual = f"unavailable: {type(exc).__name__}"
        log.warning("search: the SigLIP text model could not be loaded: %s", exc)
    with ctx.write() as s:
        prov = provenance.record(
            s, provenance.ProvenanceInfo(kind="search", algorithm_version=SEARCH_VERSION)
        )
        n = sqlite_fts.replace_all(s, index_rows(s))
        top = _top_subjects(s, SUGGESTIONS)
        s.merge(ProjectMeta(key=SUGGESTIONS_KEY, value=json.dumps(top)))
    ctx.project.artifacts.put_json("search", key, {"rows": n, "visual": visual}, provenance_id=prov)
    return {"rows": n, "visual": visual, "suggestions": len(top)}


def _top_subjects(s: Session, limit: int) -> list[str]:
    """The trip's most common subjects, counted asset by asset (bounded memory)."""
    counts: Counter[str] = Counter()
    for asset_id in s.scalars(select(Asset.id).where(Asset.status == "ok")):
        ids = list(s.scalars(select(Segment.id).where(Segment.asset_id == asset_id)))
        for data in _observations(s, ids).values():
            for subject in data.get("subjects", [])[:3]:
                counts[str(subject).lower()] += 1
    return [w for w, _ in counts.most_common(limit)]


def search_index_spec(deps: list[int | tuple[str, int]] | None = None) -> TaskSpec:
    """The index task that ends a chain (after dispositions, beside summaries; every
    mode)."""
    return TaskSpec(
        kind="library.search_index",
        stage="search index",
        resource_class=ResourceClass.CPU,
        params={"final": True},
        label="search index",
        deps=deps or [],
    )


SEARCH_STAGE = inventory.StageDef(
    "search index", "library.search_index", ResourceClass.CPU, after=("dispositions",)
)


# --------------------------------------------------------------------- query


@dataclass
class Hit:
    segment_id: int
    asset_id: int
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    sample_id: int | None = None  # the frame to show


@dataclass
class Results:
    hits: list[Hit]
    visual: str  # "ok" | "unavailable" (text model missing) | "off" (speech mode)


def fuse(rankings: list[list[int]]) -> dict[int, float]:
    """Reciprocal rank fusion: ``Σ 1 / (RRF_K + rank)`` over the rankings."""
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            score[item] = score.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return score


def _segment_of_samples(s: Session, sample_ids: list[int]) -> dict[int, tuple[int, int]]:
    """sample id → (segment id, asset id), in one query per chunk: the segment whose range
    holds the sample (a photo's one-frame segment included), for kept samples of assets
    that are ok."""
    out: dict[int, tuple[int, int]] = {}
    for chunk in range(0, len(sample_ids), 500):
        rows = s.execute(
            select(SampleFrame.id, Segment.id, Segment.asset_id)
            .join(Segment, Segment.asset_id == SampleFrame.asset_id)
            .join(Asset, Asset.id == Segment.asset_id)
            .where(
                SampleFrame.id.in_(sample_ids[chunk : chunk + 500]),
                SampleFrame.kept.is_(True),
                Asset.status == "ok",
                or_(
                    (Segment.start_ticks <= SampleFrame.ticks)
                    & (SampleFrame.ticks < Segment.end_ticks),
                    (Segment.start_ticks == Segment.end_ticks)
                    & (Segment.start_ticks == SampleFrame.ticks),
                ),
            )
        )
        for sid, gid, aid in rows:
            out.setdefault(sid, (gid, aid))
    return out


def _visual(
    s: Session, embedder: Any, query: str, limit: int
) -> list[tuple[int, int, int, float]] | None:
    """(segment, asset, best sample, distance), nearest first; None when the text model
    is not on this computer yet (the index job fetches it)."""
    index = sqlite_vec_index.index_name(embedder.model, embedder.dim, "sample")
    if not sqlite_vec_index.exists(s, index):
        return []
    try:
        vec = np.asarray(embedder.embed_text([query], local_only=True)[0], dtype=np.float32)
    except FileNotFoundError:
        return None
    hits = sqlite_vec_index.knn(s, index, vec, max(VISUAL_CANDIDATES, limit * 8))
    owners = dict(
        s.execute(
            select(Embedding.id, Embedding.owner_id).where(Embedding.id.in_([e for e, _ in hits]))
        ).all()
    )
    seg_of = _segment_of_samples(s, list(owners.values()))
    best: dict[int, tuple[int, int, int, float]] = {}
    for emb_id, dist in hits:
        sample = owners.get(emb_id)
        if sample is None or sample not in seg_of:
            continue
        gid, aid = seg_of[sample]
        if gid not in best:
            best[gid] = (gid, aid, sample, float(dist))
        if len(best) >= limit:
            break
    return list(best.values())


FIELDS = {"all": ("visual", "tags", "speech"), "visual": ("visual", "tags"), "speech": ("speech",)}


def search(
    s: Session, embedder: Any | None, query: str, mode: str = "all", limit: int = 50
) -> Results:
    """Ranked segments for ``query`` (see the module docstring). Only reads."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    hits: dict[int, Hit] = {}
    rankings: list[list[int]] = []
    visual_state = "off"
    if mode in ("all", "visual") and embedder is not None:
        visual = _visual(s, embedder, query, limit * 2)
        visual_state = "unavailable" if visual is None else "ok"
        visual = visual or []
        rankings.append([v[0] for v in visual])
        obs = _observations(s, [v[0] for v in visual])
        for gid, aid, sample, _ in visual:
            h = hits.setdefault(gid, Hit(gid, aid))
            h.sample_id = h.sample_id or sample
            tags = ", ".join((obs.get(gid) or {}).get("subjects", [])[:4])
            h.matched.append(f"looks like: {tags}" if tags else "looks like the query")
    order: list[int] = []
    for t in sqlite_fts.search(s, query, FIELDS[mode], limit * 4):
        if t.segment_id not in order:
            order.append(t.segment_id)
        label = {"speech": "said", "visual": "described", "tags": "tagged"}[t.field]
        hits.setdefault(t.segment_id, Hit(t.segment_id, 0)).matched.append(f"{label}: {t.snippet}")
    rankings.append(order)
    for gid, score in fuse(rankings).items():
        hits[gid].score = score
    out = sorted(hits.values(), key=lambda h: (-h.score, h.segment_id))[:limit]
    _fill(s, [h for h in out if not h.asset_id or h.sample_id is None])
    for h in out:
        h.matched = list(dict.fromkeys(h.matched))[:3]
    return Results(out, visual_state)


def _fill(s: Session, hits: list[Hit]) -> None:
    """Asset and the first kept frame for text-only hits, in two queries."""
    if not hits:
        return
    by_id = {h.segment_id: h for h in hits}
    for gid, aid in s.execute(
        select(Segment.id, Segment.asset_id).where(Segment.id.in_(list(by_id)))
    ):
        by_id[gid].asset_id = aid
    need = [gid for gid, h in by_id.items() if h.sample_id is None]
    if not need:
        return
    first = (
        select(Segment.id.label("gid"), func.min(SampleFrame.ticks).label("t"))
        .join(SampleFrame, SampleFrame.asset_id == Segment.asset_id)
        .where(
            Segment.id.in_(need),
            SampleFrame.kept.is_(True),
            SampleFrame.ticks >= Segment.start_ticks,
            SampleFrame.ticks
            <= case(
                (Segment.end_ticks > Segment.start_ticks, Segment.end_ticks),
                else_=Segment.start_ticks,
            ),
        )
        .group_by(Segment.id)
        .subquery()
    )
    for gid, sid in s.execute(
        select(first.c.gid, func.min(SampleFrame.id))
        .join(Segment, Segment.id == first.c.gid)
        .join(
            SampleFrame,
            (SampleFrame.asset_id == Segment.asset_id) & (SampleFrame.ticks == first.c.t),
        )
        .where(SampleFrame.kept.is_(True))
        .group_by(first.c.gid)
    ):
        by_id[gid].sample_id = sid


def suggestions(s: Session) -> list[str]:
    """The trip's own most common subjects (S12), stored by the index stage."""
    row = s.get(ProjectMeta, SUGGESTIONS_KEY)
    return list(json.loads(row.value)) if row else []


def describe(s: Session, hits: list[Hit]) -> list[dict[str, Any]]:
    """API items: segment, asset, time range (exact), status, frame, reasons."""
    ids = [h.segment_id for h in hits]
    disp = effective(s, ids)
    segs = {g.id: g for g in s.scalars(select(Segment).where(Segment.id.in_(ids)))}
    tbs = dict(
        s.execute(select(Asset.id, Asset.tb).where(Asset.id.in_({h.asset_id for h in hits}))).all()
    )
    out = []
    for h in hits:
        g = segs.get(h.segment_id)
        if g is None:
            continue
        tb = tbs.get(h.asset_id) or "1/1"
        d = disp.get(h.segment_id)
        out.append(
            {
                "segment_id": h.segment_id,
                "asset_id": h.asset_id,
                "start": {"ticks": g.start_ticks, "tb": tb},
                "end": {"ticks": g.end_ticks, "tb": tb},
                "sample_id": h.sample_id,
                "status": d.status if d else "USE",
                "score": round(h.score, 6),
                "matched": h.matched,
            }
        )
    return out
