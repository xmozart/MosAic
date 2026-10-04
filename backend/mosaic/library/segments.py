"""Segments (ARCHITECTURE.md §5.3, §8 stage 8): editorially coherent 1–20 s pieces of shots.

Shots longer than ``MAX_SEG`` are split at the strongest visual change (sample embedding
distance) or motion change inside the allowed window, never inside a spoken sentence and
never across a shot cut. ``usable_range`` trims camera start/stop wobble at the start and
end of each recording, detected from shake and motion.

All positions are logical source ticks in the asset time base.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np
from sqlalchemy import select

from mosaic.core.keys import artifact_key
from mosaic.core.time import Rounding, SourceTime, parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.embedder import DIM, model_id
from mosaic.library.purge import purge_segments
from mosaic.library.quality import shake_metric_name
from mosaic.media import inventory
from mosaic.storage import provenance, sqlite_vec_index
from mosaic.storage.models_project import (
    Asset,
    AudioEvent,
    Embedding,
    SampleFrame,
    Segment,
    Shot,
    TechMetric,
    TranscriptSegment,
)

SEGMENT_VERSION = "segments/2"
SPLIT_MIN = Fraction(3)  # a split never leaves a piece shorter than this
MAX_SEG = Fraction(20)
SPEECH_STRETCH = Fraction(10)  # a segment may run this much past MAX_SEG to finish a sentence
VISUAL_CHANGE = 0.12  # cosine distance between neighbouring samples counted as a change
WOBBLE_WINDOW = Fraction(3)  # camera start/stop wobble is looked for in the first/last 3 s
WOBBLE_FACTOR = 2.0  # a second is unsettled if shake or motion > factor × the asset median
# ...and above an absolute floor, so a perfectly steady recording (median 0) still has one.
WOBBLE_FLOOR = {"shake": 0.004, "shake_gyro": 0.15, "motion": 0.008}


@dataclass(frozen=True)
class Candidate:
    ticks: int
    score: float


def merge_intervals(spans: Sequence[tuple[int, int]], gap: int = 0) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def inside(t: int, spans: Sequence[tuple[int, int]]) -> tuple[int, int] | None:
    for a, b in spans:
        if a < t < b:
            return (a, b)
    return None


def split_shot(
    a: int,
    b: int,
    tb: Fraction,
    candidates: Sequence[Candidate],
    speech: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Split ``[a, b)`` into pieces of at most ``MAX_SEG`` (longer only to finish speech)."""

    def ticks(seconds: Fraction) -> int:
        return SourceTime.from_seconds(seconds, tb, Rounding.NEAREST).ticks

    max_len, min_split = ticks(MAX_SEG), ticks(SPLIT_MIN)
    stretch = ticks(SPEECH_STRETCH)
    pieces: list[tuple[int, int]] = []
    cur = a
    while b - cur > max_len:
        lo, hi = cur + min_split, min(cur + max_len, b - min_split)
        allowed = [c for c in candidates if lo <= c.ticks <= hi and not inside(c.ticks, speech)]
        if allowed:
            cut = max(allowed, key=lambda c: (c.score, -c.ticks)).ticks
        else:
            parts = -(-(b - cur) // max_len)
            cut = cur + (b - cur) // parts
            sentence = inside(cut, speech)
            if sentence is not None:
                if sentence[1] <= cur + max_len + stretch and b - sentence[1] >= min_split:
                    cut = sentence[1]
                elif sentence[0] - cur >= min_split:
                    cut = sentence[0]
        if cut <= cur or cut >= b:
            break
        pieces.append((cur, cut))
        cur = cut
    pieces.append((cur, b))
    return pieces


def usable_ranges(
    pieces: Sequence[tuple[int, int]], trim_head: int, trim_tail: int
) -> list[tuple[int, int]]:
    """Each piece clipped to ``[trim_head, trim_tail)``; a trim longer than the first or
    last piece carries into the next one (an empty range has start == end)."""
    out = []
    for a, b in pieces:
        ua = min(max(a, trim_head), b)
        ub = max(min(b, trim_tail), ua)
        out.append((ua, ub))
    return out


def unsettled_run(values: Sequence[float], median: float, floor: float, from_end: bool) -> int:
    """Number of leading (or trailing) unsettled seconds."""
    seq = list(reversed(values)) if from_end else list(values)
    limit = max(WOBBLE_FACTOR * median, floor)
    n = 0
    for v in seq:
        if v > limit:
            n += 1
        else:
            break
    return n


def _key(ctx: TaskContext, asset_id: int) -> str:
    with ctx.project.db.session() as s:
        stamp = [
            s.scalar(select(Shot.provenance_id).where(Shot.asset_id == asset_id).limit(1)),
            s.scalar(
                select(SampleFrame.provenance_id).where(SampleFrame.asset_id == asset_id).limit(1)
            ),
            sorted(
                s.scalars(
                    select(TranscriptSegment.provenance_id)
                    .where(TranscriptSegment.asset_id == asset_id)
                    .distinct()
                )
            ),
            sorted(
                s.scalars(
                    select(TechMetric.provenance_id)
                    .where(TechMetric.asset_id == asset_id)
                    .distinct()
                )
            ),
            s.scalar(
                select(Embedding.provenance_id)
                .join(SampleFrame, SampleFrame.id == Embedding.owner_id)
                .where(Embedding.owner_kind == "sample", SampleFrame.asset_id == asset_id)
                .limit(1)
            ),
        ]
    return artifact_key(
        "segments",
        project_id=ctx.project.id,
        inputs={"asset": asset_id, "upstream": stamp},
        config={
            "model": model_id(),
            "max": MAX_SEG,
            "split_min": SPLIT_MIN,
            "visual": VISUAL_CHANGE,
            "wobble": [WOBBLE_WINDOW, WOBBLE_FACTOR, WOBBLE_FLOOR],
        },
        version=SEGMENT_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("segments", _key(ctx, ctx.params["asset_id"]))


@task("library.segments", is_done=_is_done)
def segments_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    key = _key(ctx, asset_id)
    model = model_id()
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        if asset is None or asset.tb is None:
            raise PermanentError(f"asset {asset_id} has no timeline")
        tb = parse_rational(asset.tb)
        duration = asset.duration_ticks or 0
        shots = list(s.scalars(select(Shot).where(Shot.asset_id == asset_id).order_by(Shot.index)))
        samples = list(
            s.scalars(
                select(SampleFrame)
                .where(SampleFrame.asset_id == asset_id, SampleFrame.kept.is_(True))
                .order_by(SampleFrame.ticks)
            )
        )
        vec_rows = {
            r[0]: r[1]
            for r in s.execute(
                select(Embedding.owner_id, Embedding.vector).where(
                    Embedding.owner_kind == "sample",
                    Embedding.model == model,
                    Embedding.owner_id.in_([sm.id for sm in samples]),
                )
            )
        }
        sentences = merge_intervals(
            [
                (t.start_ticks, t.end_ticks)
                for t in s.scalars(
                    select(TranscriptSegment).where(TranscriptSegment.asset_id == asset_id)
                )
            ]
        )
        vad = merge_intervals(
            [
                (e.start_ticks, e.end_ticks)
                for e in s.scalars(
                    select(AudioEvent).where(
                        AudioEvent.asset_id == asset_id, AudioEvent.kind == "speech"
                    )
                )
            ]
        )
        metrics = list(
            s.scalars(
                select(TechMetric).where(
                    TechMetric.asset_id == asset_id,
                    TechMetric.name.in_(["motion", "shake", "shake_gyro"]),
                )
            )
        )
    if not shots:
        raise PermanentError(f"asset {asset_id} has no shots")
    vectors = {sid: np.frombuffer(v, dtype=np.float32) for sid, v in vec_rows.items()}
    by_name: dict[str, list[tuple[int, int, float]]] = {}
    for m in metrics:
        by_name.setdefault(m.name, []).append((m.start_ticks, m.end_ticks, m.value))
    motion = sorted(by_name.get("motion", []))
    shake_name = shake_metric_name(set(by_name))
    shake = sorted(by_name.get(shake_name, []))

    # Candidate cut points: visual changes between neighbouring samples, motion changes.
    cands: list[Candidate] = []
    with_vec = [sm for sm in samples if sm.id in vectors]
    for prev, cur in itertools.pairwise(with_vec):
        dist = 1.0 - float(vectors[prev.id] @ vectors[cur.id])
        if dist >= VISUAL_CHANGE:
            cands.append(Candidate((prev.ticks + cur.ticks) // 2, dist))
    if len(motion) > 2:
        diffs = [abs(b[2] - a[2]) for a, b in itertools.pairwise(motion)]
        med = statistics.median(diffs) or 1e-9
        for (_, _, va), (start, _, vb) in itertools.pairwise(motion):
            jump = abs(vb - va)
            if jump > 3 * med:
                cands.append(Candidate(start, min(0.5, jump / (10 * med)) * VISUAL_CHANGE))

    pieces: list[tuple[int, int, int]] = []  # (shot id, start, end)
    for sh in shots:
        shot_cands = [c for c in cands if sh.start_ticks < c.ticks < sh.end_ticks]
        for a, b in split_shot(sh.start_ticks, sh.end_ticks, tb, shot_cands, sentences):
            pieces.append((sh.id, a, b))

    # usable_range: trim wobble at the recording's start and end.
    window = SourceTime.from_seconds(WOBBLE_WINDOW, tb).ticks
    trim_head, trim_tail = 0, duration
    for name, series in ((shake_name, shake), ("motion", motion)):
        if not series:
            continue
        med = statistics.median(v for _, _, v in series)
        floor = WOBBLE_FLOOR[name]
        head = [v for a, _, v in series if a < window]
        tail = [v for a, _, v in series if a >= duration - window]
        n_head = unsettled_run(head, med, floor, from_end=False)
        n_tail = unsettled_run(tail, med, floor, from_end=True)
        if n_head:
            trim_head = max(trim_head, series[n_head - 1][1])
        if n_tail:
            trim_tail = min(trim_tail, series[len(series) - n_tail][0])
    usable = usable_ranges([(a, b) for _, a, b in pieces], trim_head, trim_tail)

    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="segments", algorithm_version=SEGMENT_VERSION, input_keys=[key]
            ),
        )
        index = sqlite_vec_index.ensure_index(s, model, DIM, "segment")
        purge_segments(s, asset_id)
        for i, (shot_id, a, b) in enumerate(pieces):
            ua, ub = usable[i]
            seg = Segment(
                asset_id=asset_id,
                shot_id=shot_id,
                index=i,
                start_ticks=a,
                end_ticks=b,
                usable_start_ticks=ua,
                usable_end_ticks=ub,
                has_speech=any(x < b and y > a for x, y in vad),
                provenance_id=prov,
            )
            s.add(seg)
            s.flush()
            members = [vectors[sm.id] for sm in with_vec if a <= sm.ticks < b]
            if not members:  # very short segment: nearest sample of the same shot
                same = [sm for sm in with_vec if sm.shot_id == shot_id] or with_vec
                if same:
                    near = min(same, key=lambda sm: abs(sm.ticks - (a + b) // 2))
                    members = [vectors[near.id]]
            if members:
                pooled = np.mean(members, axis=0)
                pooled = (pooled / max(float(np.linalg.norm(pooled)), 1e-12)).astype(np.float32)
                emb = Embedding(
                    owner_kind="segment",
                    owner_id=seg.id,
                    model=model,
                    dim=DIM,
                    vector=pooled.tobytes(),
                    provenance_id=prov,
                )
                s.add(emb)
                s.flush()
                sqlite_vec_index.upsert(s, index, emb.id, pooled)
    ctx.project.artifacts.put_json("segments", key, {"segments": len(pieces)}, provenance_id=prov)
    return {"segments": len(pieces)}


inventory.ASSET_STAGES.append(
    inventory.StageDef(
        "segments",
        "library.segments",
        ResourceClass.CPU,
        after=("visual", "audio", "embed", "telemetry"),
    )
)
