"""Bursts and photo + video captures of one moment (MEDIA_SUPPORT.md §3, ADR 0026).

- **Burst.** Photos from one camera taken under a second apart that look nearly the same.
  The group recommends its best frame: the highest quality (sharpness up, clipping down)
  among photos that are not rejected.
- **Capture** (``kind = "capture"``). Photos and the video segments filmed around the
  same instant (within ``MOMENT_WINDOW``) that look alike, merged when they share a clip.
  The editor then knows they show one moment and does not show both unless asked. (Not
  the segment-level *Moment* of ARCHITECTURE.md §5.2.)

Times compare only when both carry a UTC offset or both are camera-local; a naive time
is never compared with an offset-aware one (ADR 0025). No AI is used. Groups are
rebuilt from their inputs whenever those change.
"""

from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Any

import numpy as np
from sqlalchemy import delete, select

from mosaic.ai.registry import task_embedder
from mosaic.core.keys import artifact_key
from mosaic.core.time import parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import task
from mosaic.library import dispositions as _dispositions  # noqa: F401 - registers first
from mosaic.library.dispositions import effective
from mosaic.library.similarity import asset_quality
from mosaic.media import inventory
from mosaic.storage import provenance
from mosaic.storage.models_project import (
    Asset,
    Embedding,
    PhotoGroup,
    PhotoGroupMember,
    Segment,
    TechMetric,
)

MOMENTS_VERSION = "moments/1"
BURST_GAP = Fraction(1)  # seconds between consecutive burst photos ("under 1 s apart")
BURST_MAX_DISTANCE = 0.15  # cosine distance between consecutive burst photos
MOMENT_WINDOW = Fraction(10)  # seconds around a photo in which video can show the moment
MOMENT_MAX_DISTANCE = 0.2  # photo vs video frame: different sensors, so looser
PHOTO_KINDS = ("photo", "live_photo")


@dataclass(frozen=True)
class PhotoItem:
    segment_id: int
    asset_id: int
    time: datetime
    device: tuple[str | None, str | None]
    vec: np.ndarray
    quality: float  # filled in for burst members only (see ``_with_quality``)
    rejected: bool


@dataclass(frozen=True)
class VideoItem:
    segment_id: int
    start: datetime
    end: datetime
    vec: np.ndarray


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance of two L2-normalized vectors."""
    return 1.0 - float(np.dot(a, b))


def _comparable(a: datetime, b: datetime) -> bool:
    return (a.tzinfo is None) == (b.tzinfo is None)


def bursts(photos: list[PhotoItem]) -> list[list[PhotoItem]]:
    """Runs of photos from one camera, each under ``BURST_GAP`` after the previous one and
    within ``BURST_MAX_DISTANCE`` of it. Only runs of two or more are bursts."""
    out: list[list[PhotoItem]] = []
    by_device: dict[tuple[str | None, str | None], list[PhotoItem]] = {}
    for p in photos:
        by_device.setdefault(p.device, []).append(p)
    gap = timedelta(seconds=float(BURST_GAP))  # transient: a timedelta bound
    for items in by_device.values():
        aware = sorted((p for p in items if p.time.tzinfo), key=lambda p: (p.time, p.segment_id))
        naive = sorted(
            (p for p in items if not p.time.tzinfo), key=lambda p: (p.time, p.segment_id)
        )
        for seq in (aware, naive):
            run: list[PhotoItem] = []
            for p in seq:
                if run and (
                    p.time - run[-1].time >= gap
                    or distance(p.vec, run[-1].vec) > BURST_MAX_DISTANCE
                ):
                    if len(run) >= 2:
                        out.append(run)
                    run = []
                run.append(p)
            if len(run) >= 2:
                out.append(run)
    return out


def best_of(members: list[PhotoItem]) -> int:
    """The recommended frame: the best quality among photos not rejected (if all are
    rejected, among all), ties broken by the earliest."""
    pool = [p for p in members if not p.rejected] or members
    return min(pool, key=lambda p: (-p.quality, p.time, p.segment_id)).segment_id


def moments(photo: PhotoItem, videos: list[VideoItem]) -> list[int]:
    """Video segments within ``MOMENT_WINDOW`` of the photo that look alike."""
    window = timedelta(seconds=float(MOMENT_WINDOW))
    out = []
    for v in videos:
        if not (_comparable(photo.time, v.start) and _comparable(photo.time, v.end)):
            continue
        if v.end < photo.time - window or v.start > photo.time + window:
            continue
        if distance(photo.vec, v.vec) <= MOMENT_MAX_DISTANCE:
            out.append(v.segment_id)
    return out


def _time(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


CHUNK = 500  # ids per IN (...) list (SQLite's variable limit)


def _chunks(ids: list[int]) -> list[list[int]]:
    return [ids[i : i + CHUNK] for i in range(0, len(ids), CHUNK)]


def _vectors(s: Any, kind: str, ids: list[int], model: str) -> dict[int, np.ndarray]:
    out = {}
    for chunk in _chunks(ids):
        for owner, blob in s.execute(
            select(Embedding.owner_id, Embedding.vector).where(
                Embedding.owner_kind == kind,
                Embedding.model == model,
                Embedding.owner_id.in_(chunk),
            )
        ):
            out[owner] = np.frombuffer(blob, dtype=np.float32)
    return out


def _effective(s: Any, ids: list[int]) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for chunk in _chunks(ids):
        out |= effective(s, chunk)
    return out


def _photos(s: Any, model: str) -> list[PhotoItem]:
    """Every analyzed photo with a capture time and an embedding, in time order. Quality
    is not computed here: only burst members need it."""
    rows = list(
        s.execute(
            select(
                Segment.id,
                Asset.id,
                Asset.capture_time,
                Asset.camera_make,
                Asset.camera_model,
            )
            .join(Asset, Asset.id == Segment.asset_id)
            .where(Asset.kind.in_(PHOTO_KINDS), Asset.status == "ok")
        )
    )
    ids = [r[0] for r in rows]
    vecs = _vectors(s, "photo_segment", ids, model)
    disp = _effective(s, ids)
    out = []
    for sid, aid, capture, make, model_name in rows:
        t = _time(capture)
        if t is None or sid not in vecs:
            continue
        d = disp.get(sid)
        rejected = bool(d and d.status == "REJECT")
        out.append(PhotoItem(sid, aid, t, (make, model_name), vecs[sid], 0.0, rejected))

    def instant(p: PhotoItem) -> tuple[bool, datetime]:
        # Offset-aware times by their UTC instant; camera-local times by wall clock.
        t = p.time.astimezone(UTC).replace(tzinfo=None) if p.time.tzinfo else p.time
        return p.time.tzinfo is None, t

    return sorted(out, key=instant)


def _with_quality(s: Any, members: list[PhotoItem]) -> list[PhotoItem]:
    return [
        replace(p, quality=asset_quality(s, p.asset_id).get(p.segment_id, 0.0)) for p in members
    ]


@dataclass(frozen=True)
class _Span:
    asset_id: int
    start: datetime
    end: datetime
    tb: Fraction


@dataclass(frozen=True)
class SpanPool:
    """Video spans of one time kind (offset-aware or camera-local), sorted by start, with
    the starts and the longest span precomputed for bisecting."""

    spans: list[_Span]
    starts: list[datetime]
    longest: timedelta

    @classmethod
    def of(cls, spans: list[_Span]) -> SpanPool:
        spans = sorted(spans, key=lambda sp: sp.start)
        longest = max((sp.end - sp.start for sp in spans), default=timedelta(0))
        return cls(spans, [sp.start for sp in spans], longest)

    def near(self, t: datetime, window: timedelta) -> list[_Span]:
        """Spans overlapping ``t ± window``: only those starting in
        ``[t - window - longest, t + window]`` can, so the scan is bounded."""
        lo = bisect.bisect_left(self.starts, t - window - self.longest)
        hi = bisect.bisect_right(self.starts, t + window)
        return [sp for sp in self.spans[lo:hi] if sp.end >= t - window]


def _video_spans(s: Any) -> tuple[SpanPool, SpanPool]:
    """Video recordings as capture-time spans: (offset-aware, camera-local)."""
    aware: list[_Span] = []
    naive: list[_Span] = []
    for a in s.scalars(select(Asset).where(Asset.kind == "video", Asset.status == "ok")):
        start = _time(a.capture_time)
        if start is None or not a.tb:
            continue
        tb = parse_rational(a.tb)
        length = timedelta(seconds=float(Fraction(a.duration_ticks or 0) * tb))
        (aware if start.tzinfo else naive).append(_Span(a.id, start, start + length, tb))
    return SpanPool.of(aware), SpanPool.of(naive)


class _VideoCache:
    """Segments and embeddings of recent videos: photos are visited in time order, so the
    same few clips are asked for again and again (bursts near one clip)."""

    def __init__(self, s: Any, model: str, size: int = 16) -> None:
        self.s, self.model, self.size = s, model, size
        self.items: dict[int, list[VideoItem]] = {}

    def get(self, span: _Span) -> list[VideoItem]:
        if span.asset_id in self.items:
            items = self.items.pop(span.asset_id)
        else:
            segs = list(
                self.s.execute(
                    select(Segment.id, Segment.start_ticks, Segment.end_ticks).where(
                        Segment.asset_id == span.asset_id
                    )
                )
            )
            vecs = _vectors(self.s, "segment", [g[0] for g in segs], self.model)
            items = [
                VideoItem(
                    sid,
                    span.start + timedelta(seconds=float(Fraction(a) * span.tb)),
                    span.start + timedelta(seconds=float(Fraction(b) * span.tb)),
                    vecs[sid],
                )
                for sid, a, b in segs
                if sid in vecs
            ]
        self.items[span.asset_id] = items  # most recent last
        while len(self.items) > self.size:
            self.items.pop(next(iter(self.items)))
        return items


def _videos_near(photo: PhotoItem, pools: tuple[SpanPool, SpanPool], cache: Any) -> list[VideoItem]:
    window = timedelta(seconds=float(MOMENT_WINDOW))
    pool = pools[0] if photo.time.tzinfo else pools[1]
    out: list[VideoItem] = []
    for sp in pool.near(photo.time, window):
        out += cache.get(sp)
    return out


def merge_captures(pairs: list[tuple[int, list[int]]]) -> list[set[int]]:
    """Photo → matching video segments, merged into groups that share any segment."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for photo, segs in pairs:
        for sid in segs:
            parent[find(photo)] = find(sid)
    groups: dict[int, set[int]] = {}
    for photo, segs in pairs:
        for x in (photo, *segs):
            groups.setdefault(find(x), set()).add(x)
    return list(groups.values())


def _key(ctx: TaskContext) -> str:
    """Every input, streamed: photo and video segments (with their embeddings'
    provenance), capture times, devices and the photos' dispositions."""
    h = hashlib.sha256()
    model = task_embedder(ctx).model
    with ctx.project.db.session() as s:
        for row in s.execute(
            select(
                Segment.id,
                Segment.provenance_id,
                Asset.kind,
                Asset.capture_time,
                Asset.camera_make,
                Asset.camera_model,
                Asset.status,
            )
            .join(Asset, Asset.id == Segment.asset_id)
            .order_by(Segment.id)
        ):
            h.update(repr(tuple(row)).encode())
        for emb in s.execute(
            select(Embedding.owner_kind, Embedding.owner_id, Embedding.provenance_id)
            .where(
                Embedding.owner_kind.in_(("segment", "photo_segment")),
                Embedding.model == model,
            )
            .order_by(Embedding.owner_kind, Embedding.owner_id)
        ):
            h.update(repr(tuple(emb)).encode())
        photo_segs = list(
            s.scalars(
                select(Segment.id)
                .join(Asset, Asset.id == Segment.asset_id)
                .where(Asset.kind.in_(PHOTO_KINDS))
                .order_by(Segment.id)
            )
        )
        disp = _effective(s, photo_segs)
        h.update(repr(sorted((k, v.status) for k, v in disp.items())).encode())
        # Best-frame quality comes from photo metrics (project percentiles).
        for metric in s.execute(
            select(TechMetric.provenance_id)
            .join(Asset, Asset.id == TechMetric.asset_id)
            .where(Asset.kind.in_(PHOTO_KINDS))
            .distinct()
            .order_by(TechMetric.provenance_id)
        ):
            h.update(f"m{metric[0]};".encode())
    return artifact_key(
        "moments",
        project_id=ctx.project.id,
        inputs=h.hexdigest(),
        config={
            "model": model,
            "burst_gap": BURST_GAP,
            "burst_max_distance": BURST_MAX_DISTANCE,
            "moment_window": MOMENT_WINDOW,
            "moment_max_distance": MOMENT_MAX_DISTANCE,
        },
        version=MOMENTS_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("moments", _key(ctx))


@task("library.moments", is_done=_is_done)
def moments_task(ctx: TaskContext) -> dict[str, Any]:
    key = _key(ctx)
    model = task_embedder(ctx).model
    with ctx.project.db.session() as s:
        photos = _photos(s, model)
        burst_groups = [_with_quality(s, run) for run in bursts(photos)]
        spans = _video_spans(s)
        cache = _VideoCache(s, model)
        pairs = []
        for p in photos:  # in time order: the cache keeps the clips nearby
            ctx.check_cancelled()
            matches = moments(p, _videos_near(p, spans, cache))
            if matches:
                pairs.append((p.segment_id, matches))
        captures = merge_captures(pairs)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="moments",
                algorithm_version=MOMENTS_VERSION,
                model=model,
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
        s.execute(delete(PhotoGroupMember))
        s.execute(delete(PhotoGroup))
        for members in burst_groups:
            g = PhotoGroup(kind="burst", best_segment_id=best_of(members), provenance_id=prov)
            s.add(g)
            s.flush()
            for p in members:
                s.add(PhotoGroupMember(group_id=g.id, segment_id=p.segment_id))
        for members_ in captures:
            g = PhotoGroup(kind="capture", best_segment_id=None, provenance_id=prov)
            s.add(g)
            s.flush()
            for sid in sorted(members_):
                s.add(PhotoGroupMember(group_id=g.id, segment_id=sid))
    result = {
        "photos": len(photos),
        "bursts": len(burst_groups),
        "captures": len(captures),
        "burst_photos": sum(len(b) for b in burst_groups),
    }
    ctx.project.artifacts.put_json("moments", key, result, provenance_id=prov)
    return result


MOMENTS_STAGE = inventory.StageDef(
    "moments", "library.moments", ResourceClass.CPU, after=("dispositions",)
)
inventory.PROJECT_STAGES.append(MOMENTS_STAGE)
