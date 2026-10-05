"""Analysis estimates (ANALYSIS_MODES.md §4; screens S8 and S25).

Computed from the project's probed inventory (footage length, clip and photo counts) and,
when the library already has them, its real segments, candidates and reviews; never from
a static example. Where a number is not knowable before analysis (how many segments a
mode finds, how many become L3 candidates) the estimate is a range.

Every value here is for display: seconds and dollars are rounded, nothing is stored or
used as an authoritative time (invariant 3).

Wall time uses per-mode speed factors measured on the M0 eval machine until the hardware
benchmark (M1 step 12) replaces them.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaic.ai.registry import limits_for, price_for
from mosaic.core.modes import ModeConfig
from mosaic.core.principal import Principal
from mosaic.core.time import parse_rational
from mosaic.library import review, vision
from mosaic.library.mosaics import PER_SEGMENT, geometry
from mosaic.storage.config import ConfigService
from mosaic.storage.models_project import Asset, DeepReview, Segment

# Mean segment length before a project has segments (M0 Airshow: 485 segments in 90 min).
SEGMENT_SECONDS = Fraction(11)
# Share of segments that become L3 candidates (not REJECT, best of their look-alikes).
L3_SHARE = (Fraction(3, 10), Fraction(6, 10))
# Output tokens actually used, as a share of the call's limit.
OUTPUT_SHARE = (Fraction(1, 4), Fraction(1))
TEXT_TOKENS = 2000  # prompt, context and schema per call
# Local analysis wall time per second of footage, by mode (M0: 90 min Balanced in 27 min).
SPEED = {"quick": Fraction(1, 8), "balanced": Fraction(3, 10), "thorough": Fraction(3, 5)}
AI_CALL_SECONDS = (4, 15)  # per call, one AI slot
WALL_SPREAD = (Fraction(7, 10), Fraction(3, 2))
SAMPLE_BYTES = 60_000  # 640 px JPEG
SHEET_BYTES = 350_000
BITRATE = {"lrf_or_540": 2_000_000, "720": 3_000_000}  # proxy bits per second


@dataclass(frozen=True)
class Estimate:
    mode: str
    scope: str  # project | deepen
    videos: int
    photos: int
    video_seconds: int  # display
    segments: int
    l2_calls: int
    l3_calls: tuple[int, int]
    cost_usd: tuple[float, float] | None  # None: no price for a configured model
    storage_bytes: int
    wall_seconds: tuple[int, int]
    days: int | None = None  # deepen: trip days in scope

    def as_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["l3_calls"] = list(self.l3_calls)
        out["cost_usd"] = list(self.cost_usd) if self.cost_usd else None
        out["wall_seconds"] = list(self.wall_seconds)
        return out


@dataclass(frozen=True)
class _Calls:
    tokens_in: int
    tokens_out: tuple[int, int]
    price: tuple[float, float] | None

    def cost(self, n: tuple[int, int]) -> tuple[float, float] | None:
        if self.price is None:
            return None
        pin, pout = self.price
        return (
            (n[0] * (self.tokens_in * pin + self.tokens_out[0] * pout)) / 1_000_000,
            (n[1] * (self.tokens_in * pin + self.tokens_out[1] * pout)) / 1_000_000,
        )


def _image_tokens(w: int, h: int) -> int:
    return w * h // 750 + 50  # the common ~750 px² per token rule for vision models


def _calls(
    config: ConfigService,
    me: Principal,
    capability: str,
    images: list[tuple[int, int]],
    max_tokens: int,
) -> _Calls:
    choice = config.provider(me, capability)
    return _Calls(
        sum(_image_tokens(w, h) for w, h in images) + TEXT_TOKENS,
        (
            math.floor(max_tokens * OUTPUT_SHARE[0]),
            math.floor(max_tokens * OUTPUT_SHARE[1]),
        ),
        price_for(choice),
    )


def _vision(config: ConfigService, me: Principal, mode: ModeConfig) -> tuple[_Calls, int]:
    limits = limits_for(config.provider(me, "vision"))
    geo = geometry(mode.tiles, limits.max_image_px)
    w, h = geo.size(geo.rows)
    return _calls(config, me, "vision", [(w, h)], vision.MAX_TOKENS), geo.capacity


def _review(config: ConfigService, me: Principal) -> _Calls:
    px = limits_for(config.provider(me, "reviewer")).max_image_px
    frame = (px, px * 9 // 16)
    return _calls(config, me, "reviewer", [frame] * review.FRAMES, review.MAX_TOKENS)


def _sum(*costs: tuple[float, float] | None) -> tuple[float, float] | None:
    if any(c is None for c in costs):
        return None
    lo = sum(c[0] for c in costs if c)
    hi = sum(c[1] for c in costs if c)
    return round(lo, 2), round(hi, 2)


def _wall(local_seconds: Fraction, calls: tuple[int, int]) -> tuple[int, int]:
    lo = local_seconds * WALL_SPREAD[0] + calls[0] * AI_CALL_SECONDS[0]
    hi = local_seconds * WALL_SPREAD[1] + calls[1] * AI_CALL_SECONDS[1]
    return math.ceil(lo), math.ceil(hi)


def _footage(session: Session, asset_ids: set[int] | None = None) -> tuple[int, int, Fraction]:
    videos, footage = 0, Fraction(0)
    q = select(Asset).where(Asset.kind == "video", Asset.status == "ok")
    for a in session.scalars(q):
        if asset_ids is not None and a.id not in asset_ids:
            continue
        videos += 1
        if a.duration_ticks and a.tb:
            footage += a.duration_ticks * parse_rational(a.tb)
    photos = session.scalar(select(func.count(Asset.id)).where(Asset.kind == "photo")) or 0
    return videos, photos, footage


def _segment_seconds(session: Session) -> Fraction:
    """The library's real mean segment length, if it has segments."""
    total = Fraction(0)
    n = 0
    for g, tb in session.execute(
        select(Segment, Asset.tb).join(Asset, Asset.id == Segment.asset_id)
    ):
        if tb:
            total += (g.end_ticks - g.start_ticks) * parse_rational(tb)
            n += 1
    return total / n if n and total > 0 else SEGMENT_SECONDS


def for_project(
    session: Session, config: ConfigService, me: Principal, mode: ModeConfig
) -> Estimate:
    """A full analysis run of the project in ``mode``."""
    videos, photos, footage = _footage(session)
    segments = math.ceil(footage / _segment_seconds(session)) if footage else 0
    samples = math.ceil(footage / mode.sample_interval) + segments
    l2 = (0, 0)
    l2_cost: tuple[float, float] | None = (0.0, 0.0)
    if mode.l2:
        calls, capacity = _vision(config, me, mode)
        n = math.ceil(segments * PER_SEGMENT / capacity)
        l2 = (n, n)
        l2_cost = calls.cost(l2)
    l3 = (0, 0)
    l3_cost: tuple[float, float] | None = (0.0, 0.0)
    if mode.l3:
        l3 = (math.floor(segments * L3_SHARE[0]), math.ceil(segments * L3_SHARE[1]))
        l3_cost = _review(config, me).cost(l3)
    proxy = footage * BITRATE[mode.proxy] / 8
    sheets = l2[1]
    storage = math.ceil(proxy + samples * SAMPLE_BYTES + sheets * SHEET_BYTES)
    speed = SPEED.get(mode.name, SPEED["balanced"])
    return Estimate(
        mode=mode.name,
        scope="project",
        videos=videos,
        photos=photos,
        video_seconds=round(footage),
        segments=segments,
        l2_calls=l2[0],
        l3_calls=l3,
        cost_usd=_sum(l2_cost, l3_cost),
        storage_bytes=storage,
        wall_seconds=_wall(footage * speed, (l2[0] + l3[0], l2[1] + l3[1])),
    )


def for_deepen(
    session: Session,
    config: ConfigService,
    me: Principal,
    scope: review.DeepenScope,
    target: ModeConfig,
) -> Estimate:
    """Deepening ``scope`` to ``target``: L2 where it is missing, then L3 on candidates
    that have no review yet. L0/L1 are reused, so no local analysis time is added."""
    scoped = review.scope_segments(session, scope)
    missing = review.l2_missing(session, scoped)
    videos, photos, footage = _footage(session, set(scoped))
    n_segments = sum(len(v) for v in scoped.values())
    l2_segments = sum(len(scoped[a]) for a in missing)
    l2 = (0, 0)
    l2_cost: tuple[float, float] | None = (0.0, 0.0)
    if missing:
        calls, capacity = _vision(config, me, target)
        n = math.ceil(l2_segments * PER_SEGMENT / capacity)
        l2 = (n, n)
        l2_cost = calls.cost(l2)
    l3 = (0, 0)
    l3_cost: tuple[float, float] | None = (0.0, 0.0)
    if target.l3:
        plan, _ = review.plan_deepen(session, scope)
        ids = [i for v in plan.values() for i in v]
        reviewed = set(
            session.scalars(select(DeepReview.segment_id).where(DeepReview.segment_id.in_(ids)))
        )
        known = len(set(ids) - reviewed)
        # Clips that get L2 first have unknown candidates until it runs.
        l3 = (
            known + math.floor(l2_segments * L3_SHARE[0]),
            known + math.ceil(l2_segments * L3_SHARE[1]),
        )
        l3_cost = _review(config, me).cost(l3)
    days = _days(session, scoped)
    return Estimate(
        mode=target.name,
        scope="deepen",
        videos=videos,
        photos=photos,
        video_seconds=round(footage),
        segments=n_segments,
        l2_calls=l2[0],
        l3_calls=l3,
        cost_usd=_sum(l2_cost, l3_cost),
        storage_bytes=l2[0] * SHEET_BYTES,
        wall_seconds=_wall(Fraction(0), (l2[0] + l3[0], l2[1] + l3[1])),
        days=days,
    )


def _days(session: Session, scoped: dict[int, list[int]]) -> int | None:
    from mosaic.editing.retrieval import capture_dates, trip_day

    assets = list(session.scalars(select(Asset).where(Asset.kind == "video")))
    first = min(capture_dates(assets).values(), default=None)
    if first is None:
        return None
    by_id = {a.id: a for a in assets}
    found = set()
    for aid, ids in scoped.items():
        a = by_id[aid]
        if a.tb is None:
            continue
        rate = parse_rational(a.tb)
        for g in session.scalars(select(Segment).where(Segment.id.in_(ids))):
            found.add(trip_day(a.capture_time, Fraction(g.start_ticks) * rate, first))
    found.discard(0)  # unknown date
    return len(found)
