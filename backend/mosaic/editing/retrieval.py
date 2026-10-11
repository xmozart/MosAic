"""Candidate retrieval (ARCHITECTURE.md §9): deterministic filters that cap the AI context.

A segment is a candidate when its effective disposition is not REJECT (the user's
decision wins, invariant 10), its usable range is at least the pace's minimum shot, and it
is the recommended pick of its similarity group (a user USE keeps any segment). When the
distinct footage is shorter than ``FALLBACK_FACTOR`` × the requested duration, the other
members of similarity groups come back as candidates (marked as similar to their group's
pick; the critic still checks repetition). When more than ``MAX_CANDIDATES`` remain, each
day keeps a share proportional to its footage, best first, so the planner sees the whole
trip. Clips are read a batch at a time (invariant 13).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.time import parse_rational
from mosaic.editing.categories import avoided, classify, weight_bonus
from mosaic.library import decisions
from mosaic.library.dispositions import (
    effective_for_clips,
    metric_window,
    shake_percentiles,
)
from mosaic.storage.models_project import (
    Asset,
    ClipDecision,
    ClipTag,
    DeepReview,
    Segment,
    TranscriptSegment,
    VisualObservation,
)

MAX_CANDIDATES = 200
FALLBACK_FACTOR = 3
MIN_PER_DAY = 3
TRANSCRIPT_CHARS = 160
INTEREST = {"low": 0.0, "medium": 1.0, "high": 2.0}
COMPOSITION = {"poor": 0.0, "fair": 0.5, "good": 1.0, "excellent": 1.5}


def seg_ref(segment_id: int) -> str:
    return f"seg_{segment_id:06d}"


def parse_ref(ref: str) -> int | None:
    if not ref.startswith("seg_") or not ref[4:].isdigit():
        return None
    return int(ref[4:])


@dataclass
class Candidate:
    segment_id: int
    asset_id: int
    shot_id: int
    tb: str
    rate: str | None
    start: int
    end: int
    usable_start: int
    usable_end: int
    has_speech: bool
    status: str  # USE|MAYBE (effective)
    user_use: bool
    capture: datetime | None
    day: int  # 1-based trip day, 0 when unknown
    quality: float | None
    group_id: int | None
    shake_percentile: float | None
    transcript: str = ""
    obs: dict[str, Any] = field(default_factory=dict)
    similar_to: int | None = None  # the group's recommended segment, for non-best members
    categories: frozenset[str] = frozenset()  # content categories (ADR 0072)
    bonus: float = 0.0  # the owner's content weights for those categories

    @property
    def ref(self) -> str:
        return seg_ref(self.segment_id)

    @property
    def usable_seconds(self) -> Fraction:
        return Fraction(self.usable_end - self.usable_start) * parse_rational(self.tb)

    def score(self) -> float:
        s = INTEREST.get(self.obs.get("interest", ""), 1.0)
        s += COMPOSITION.get(self.obs.get("composition", ""), 0.5)
        s += 0.5 * (self.quality or 0.0)
        s += 1.0 if self.status == "USE" else 0.0
        s += 3.0 if self.user_use else 0.0
        return s + self.bonus

    def sort_key(self) -> tuple[str, int, int]:
        when = self.capture.isoformat() if self.capture else ""
        return (when, self.asset_id, self.start)

    def line(self) -> str:
        """One compact line for the planner."""
        dur = float(self.usable_seconds)
        when = self.capture.strftime("%H:%M") if self.capture else "--:--"
        o = self.obs
        parts = [
            self.ref,
            f"day {self.day}" if self.day else "day ?",
            when,
            f"{dur:.1f}s",
            f"{o.get('shot_type', '?')}/{o.get('camera_motion', '?')}",
            f"interest {o.get('interest', '?')}",
        ]
        if self.has_speech and self.transcript:
            parts.append(f'speech "{self.transcript[:80]}"')
        elif self.has_speech:
            parts.append("speech")
        if self.similar_to is not None:
            parts.append(f"similar to {seg_ref(self.similar_to)}")
        parts.append(o.get("description", "(no description)"))
        return " · ".join(parts)

    def detail(self) -> str:
        """A fuller description for the selector."""
        o = self.obs
        bits = [self.line()]
        extra = []
        if o.get("subjects"):
            extra.append("subjects: " + ", ".join(o["subjects"]))
        if o.get("people"):
            extra.append(f"people: {o['people']}")
        if o.get("composition"):
            extra.append(f"composition: {o['composition']}")
        if o.get("issues"):
            extra.append("issues: " + ", ".join(o["issues"]))
        if self.status == "MAYBE":
            extra.append("disposition: MAYBE")
        if self.has_speech and self.transcript:
            extra.append(f'transcript: "{self.transcript}"')
        if extra:
            bits.append("   " + "; ".join(extra))
        return "\n".join(bits)


def _capture(asset: Asset) -> datetime | None:
    if not asset.capture_time:
        return None
    text = asset.capture_time.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def first_capture_date(session: Session) -> date | None:
    """Day 1 of the trip: the earliest local capture date of any video asset, streamed
    (invariant 13). The same rule as ``capture_dates`` over every video."""
    first: date | None = None
    q = select(Asset.capture_time).where(Asset.kind == "video", Asset.capture_time.is_not(None))
    for ct in session.scalars(q.execution_options(yield_per=1000)):
        if not ct:
            continue
        try:
            d = datetime.fromisoformat(ct.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        first = d if first is None or d < first else first
    return first


def capture_dates(assets: list[Asset]) -> dict[int, date]:
    """Asset id → local capture date (each in its own recorded offset), when known."""
    out = {}
    for a in assets:
        c = _capture(a)
        if c is not None:
            out[a.id] = c.date()
    return out


def trip_day(capture_time: str | None, offset_s: Fraction, first: date | None) -> int:
    """1-based trip day of a moment ``offset_s`` into a recording; 0 when unknown. Dates,
    not datetimes, are compared, so recordings with and without a UTC offset mix."""
    if first is None or not capture_time:
        return 0
    try:
        start = datetime.fromisoformat(capture_time.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return ((start + timedelta(seconds=float(offset_s))).date() - first).days + 1


CLIP_BATCH = 64  # clips read together: a few queries per batch, memory bounded by it


class _Seg(NamedTuple):
    """The segment columns retrieval reads (rows, not ORM objects: a 40-hour library has
    over 11,000 segments)."""

    id: int
    asset_id: int
    shot_id: int
    start_ticks: int
    end_ticks: int
    usable_start_ticks: int
    usable_end_ticks: int
    has_speech: bool
    quality: float | None
    similarity_group_id: int | None
    group_best: bool


_SEG_COLUMNS = tuple(getattr(Segment, f) for f in _Seg._fields)


@dataclass
class _Clip:
    """One clip's segments with what retrieval reads about them."""

    asset: Asset
    segments: list[_Seg]
    rules: dict[int, decisions.SegmentDecision]  # the decision in force per segment
    obs: dict[int, dict[str, Any]]
    tags: list[str] = field(default_factory=list)  # the owner's tags on the clip


def _clips(session: Session, assets: list[Asset]) -> Iterator[_Clip]:
    """The clips with segments, in order, read ``CLIP_BATCH`` at a time (invariant 13):
    a handful of queries per batch rather than per clip (ADR 0065)."""
    for n in range(0, len(assets), CLIP_BATCH):
        batch = assets[n : n + CLIP_BATCH]
        ids = [a.id for a in batch]
        segs: dict[int, list[_Seg]] = {}
        for row in session.execute(
            select(*_SEG_COLUMNS).where(Segment.asset_id.in_(ids)).order_by(Segment.id)
        ):
            g = _Seg(*row)
            segs.setdefault(g.asset_id, []).append(g)
        if not segs:
            continue
        rows = effective_for_clips(session, ids)
        clip_rules = {
            d.asset_id: d
            for d in session.scalars(select(ClipDecision).where(ClipDecision.asset_id.in_(ids)))
        }
        in_batch = select(Segment.id).where(Segment.asset_id.in_(ids))
        seen = {
            o.segment_id: o.data
            for o in session.scalars(
                select(VisualObservation).where(VisualObservation.segment_id.in_(in_batch))
            )
        }
        seen |= {  # L3 (full resolution) supersedes L2
            r.segment_id: r.data
            for r in session.scalars(select(DeepReview).where(DeepReview.segment_id.in_(in_batch)))
        }
        tags: dict[int, list[str]] = {}
        for aid, tag in session.execute(
            select(ClipTag.asset_id, ClipTag.tag).where(ClipTag.asset_id.in_(ids))
        ):
            tags.setdefault(aid, []).append(tag)
        for asset in batch:
            gs = segs.get(asset.id)
            if not gs:
                continue
            yield _Clip(
                asset,
                gs,
                # The owner's decisions first: on the segment, then on the clip (ADR 0042).
                decisions.resolve(gs, rows, clip_rules.get(asset.id)),
                {g.id: seen[g.id] for g in gs if g.id in seen},
                sorted(tags.get(asset.id, [])),
            )


def _describe(session: Session, cands: list[Candidate]) -> None:
    """Fill in what only the final candidates need: their shake and their words. Ranking
    and capping never read them, so a 40-hour library reads them for 200 segments, not
    for every one (ADR 0065)."""
    windows: dict[int, list[tuple[int, int, int]]] = {}
    for c in cands:
        windows.setdefault(c.asset_id, []).append(
            (c.segment_id, *metric_window(c.start, c.end, c.usable_start, c.usable_end))
        )
    shake = shake_percentiles(session, windows)
    for c in cands:
        found = shake.get(c.segment_id)
        c.shake_percentile = statistics.median(found) if found else None
    speaking = sorted({c.asset_id for c in cands if c.has_speech})
    speech: dict[int, list[tuple[int, int, str]]] = {}
    for n in range(0, len(speaking), CLIP_BATCH):
        for aid, start, end, text in session.execute(
            select(
                TranscriptSegment.asset_id,
                TranscriptSegment.start_ticks,
                TranscriptSegment.end_ticks,
                TranscriptSegment.text,
            )
            .where(TranscriptSegment.asset_id.in_(speaking[n : n + CLIP_BATCH]))
            .order_by(TranscriptSegment.start_ticks, TranscriptSegment.id)
        ):
            speech.setdefault(aid, []).append((start, end, text))
    for c in cands:
        if c.has_speech:
            a, b = c.usable_start, c.usable_end
            texts = (t.strip() for st, en, t in speech.get(c.asset_id, []) if st < b and en > a)
            c.transcript = " ".join(t for t in texts if t)[:TRANSCRIPT_CHARS]


def retrieve(
    session: Session,
    min_seconds: Fraction,
    want_seconds: Fraction,
    weights: Mapping[str, str] | None = None,
    keep: frozenset[int] = frozenset(),
) -> tuple[list[Candidate], dict[str, int]]:
    """All eligible candidates (capped), sorted by capture time, plus filter counts.
    ``keep``: segment ids a storyboard locked; a content weight never avoids them
    (invariant 10)."""
    weights = weights or {}
    counts = {"segments": 0, "rejected": 0, "too_short": 0, "duplicate": 0, "analysis_only": 0}
    if any(w == "avoid" for w in weights.values()):
        counts["avoided"] = 0
    found: list[Candidate] = []
    similar: list[Candidate] = []
    best_of: dict[int, int] = {
        gid: sid
        for sid, gid in session.execute(
            select(Segment.id, Segment.similarity_group_id).where(Segment.group_best.is_(True))
        )
        if gid is not None
    }
    assets = list(session.scalars(select(Asset).where(Asset.kind == "video").order_by(Asset.id)))
    first_day = min(capture_dates(assets).values(), default=None)
    eligible = []
    for asset in assets:
        if asset.tb is None:
            continue
        if "analysis_only" in (asset.flags or []):
            # Raw 360 footage: analyzed through a forward view, never cut into an edit
            # until reframing exists (MEDIA_SUPPORT.md §2, ADR 0024).
            counts["analysis_only"] += 1
            continue
        eligible.append(asset)
    for clip in _clips(session, eligible):
        asset, segs, disp, obs = clip.asset, clip.segments, clip.rules, clip.obs
        assert asset.tb is not None
        tb = parse_rational(asset.tb)
        base = _capture(asset)
        for g in segs:
            counts["segments"] += 1
            d = disp.get(g.id)
            status = (d.status if d else None) or "USE"
            user_use = bool(d and d.forced)
            if status == "REJECT":
                counts["rejected"] += 1
                continue
            usable = Fraction(g.usable_end_ticks - g.usable_start_ticks) * tb
            if usable < min_seconds and not user_use:
                counts["too_short"] += 1
                continue
            cats = classify(
                obs.get(g.id, {}), has_speech=g.has_speech, rate=asset.rate, tags=clip.tags
            )
            if weights and avoided(cats, weights) and not user_use and g.id not in keep:
                counts["avoided"] += 1  # the owner asked to avoid it (ADR 0072)
                continue
            duplicate = g.similarity_group_id is not None and not g.group_best and not user_use
            capture = (
                base + timedelta(seconds=float(Fraction(g.start_ticks) * tb)) if base else None
            )
            day = trip_day(asset.capture_time, Fraction(g.start_ticks) * tb, first_day)
            (similar if duplicate else found).append(
                Candidate(
                    segment_id=g.id,
                    asset_id=asset.id,
                    shot_id=g.shot_id,
                    tb=asset.tb,
                    rate=asset.rate,
                    start=g.start_ticks,
                    end=g.end_ticks,
                    usable_start=g.usable_start_ticks,
                    usable_end=g.usable_end_ticks,
                    has_speech=g.has_speech,
                    status="USE" if status == "USE" else "MAYBE",
                    user_use=user_use,
                    capture=capture,
                    day=day,
                    quality=g.quality,
                    group_id=g.similarity_group_id,
                    shake_percentile=None,  # read for the final candidates only
                    obs=obs.get(g.id, {}),
                    similar_to=best_of.get(g.similarity_group_id or -1) if duplicate else None,
                    categories=cats,
                    bonus=weight_bonus(cats, weights),
                )
            )
    counts["duplicate"] = len(similar)
    if sum((c.usable_seconds for c in found), Fraction(0)) < FALLBACK_FACTOR * want_seconds:
        found += similar
        counts["duplicate_fallback"] = len(similar)
    capped = cap_by_day(found, MAX_CANDIDATES, keep)
    _describe(session, capped)
    counts["candidates"] = len(capped)
    counts["capped"] = len(found) - len(capped)
    return sorted(capped, key=Candidate.sort_key), counts


def cap_by_day(
    cands: list[Candidate], limit: int, locked: frozenset[int] = frozenset()
) -> list[Candidate]:
    """Keep at most ``limit``: every user USE and every segment a storyboard locked
    (``locked``), then per day a share proportional to its candidates (at least
    ``MIN_PER_DAY``), best score first."""
    if len(cands) <= limit:
        return list(cands)
    forced = [c for c in cands if c.user_use or c.segment_id in locked]
    rest = [c for c in cands if not (c.user_use or c.segment_id in locked)]
    room = max(0, limit - len(forced))
    by_day: dict[int, list[Candidate]] = {}
    for c in rest:
        by_day.setdefault(c.day, []).append(c)
    total = len(rest)
    keep: list[Candidate] = []
    for _day, items in sorted(by_day.items()):
        share = max(MIN_PER_DAY, round(room * len(items) / total))
        items.sort(key=lambda c: (-c.score(), c.segment_id))
        keep.extend(items[:share])
    if len(keep) > room:
        keep.sort(key=lambda c: (-c.score(), c.segment_id))
        keep = keep[:room]
    return forced + keep
