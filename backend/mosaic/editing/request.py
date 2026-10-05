"""The edit request (PRODUCT.md §4), pace in frames, and the timeline rate (M0 defaults)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mosaic.core.time import Rounding, format_rational, parse_rational, round_fraction

Chronology = Literal["strict", "mostly", "thematic", "story"]
Pace = Literal["very_slow", "slow", "balanced", "energetic", "fast", "very_fast"]

STORY_PRESETS: dict[str, str] = {
    "chronological_diary": "A day-by-day diary of the trip in the order it happened.",
    "cinematic_journey": "A cinematic journey: strong establishing shots, a sense of "
    "travel and place, emotional high points, a calm, memorable ending.",
    "adventure_highlights": "The most exciting activities and moments, energetic.",
    "family_memories": "The people and shared moments that the family will want to keep.",
    "people_first": "People, faces, reactions and interactions over scenery.",
    "nature": "Landscapes, water, sky, plants and natural sound.",
    "wildlife": "Animals and wildlife encounters.",
    "food_culture": "Food, markets, traditions and local culture.",
    "city": "Streets, architecture and city life.",
    "road_trip": "The journey itself: roads, vehicles, stops along the way.",
    "relaxed": "Slow, calm moments; long holds and natural sound.",
    "high_energy_montage": "Fast, energetic montage of the best action.",
    "documentary": "An informative documentary that lets speech and context lead.",
    "funny_moments": "Light-hearted, funny moments and reactions.",
    "drone_showcase": "Aerial footage first, supported by ground shots.",
    "event_recap": "A recap of the event from arrival to finale.",
}

# (min, preferred, max) seconds per pace; dialogue may run to DIALOGUE_MAX.
PACE_SECONDS: dict[str, tuple[Fraction, Fraction, Fraction]] = {
    "very_slow": (Fraction(3), Fraction(7), Fraction(15)),
    "slow": (Fraction(5, 2), Fraction(11, 2), Fraction(12)),
    "balanced": (Fraction(3, 2), Fraction(7, 2), Fraction(8)),
    "energetic": (Fraction(1), Fraction(5, 2), Fraction(5)),
    "fast": (Fraction(7, 10), Fraction(9, 5), Fraction(7, 2)),
    "very_fast": (Fraction(1, 2), Fraction(6, 5), Fraction(5, 2)),
}
DIALOGUE_MAX = Fraction(20)

FPS_ALIASES = {
    "23.976": "24000/1001",
    "29.97": "30000/1001",
    "59.94": "60000/1001",
    "47.952": "48000/1001",
    "119.88": "120000/1001",
}


def parse_fps(value: str) -> str:
    """``29.97`` → ``30000/1001``; integers and rationals pass through (canonical form)."""
    text = value.strip()
    rate = parse_rational(FPS_ALIASES.get(text, text))
    if rate <= 0 or rate > 240:
        raise ValueError(f"unsupported frame rate {value!r}")
    return format_rational(rate)


class EditRequest(BaseModel):
    """What the user asked for. ``duration_s`` is the user's whole-second choice; the
    authoritative target is ``Plan.target_frames`` at the timeline rate."""

    model_config = ConfigDict(extra="forbid")

    duration_s: int = Field(ge=5, le=4 * 3600)
    story: str = "cinematic_journey"
    chronology: Chronology = "mostly"
    pace: Pace = "balanced"
    tolerance_pct: int = Field(default=5, ge=0, le=25)
    instructions: str = Field(default="", max_length=2000)
    fps: str | None = None  # rational; None = dominant source rate
    variant: int = Field(default=0, ge=0)

    @field_validator("story")
    @classmethod
    def _story(cls, v: str) -> str:
        if v not in STORY_PRESETS:
            raise ValueError(f"unknown story {v!r}; choose one of {', '.join(STORY_PRESETS)}")
        return v

    @field_validator("fps")
    @classmethod
    def _fps(cls, v: str | None) -> str | None:
        return None if v is None else parse_fps(v)


@dataclass(frozen=True)
class PaceFrames:
    min: int
    preferred: int
    max: int
    dialogue_max: int


def pace_frames(pace: str, rate: str) -> PaceFrames:
    lo, pref, hi = PACE_SECONDS[pace]
    r = parse_rational(rate)

    def f(s: Fraction) -> int:
        return round_fraction(s * r, Rounding.NEAREST)

    return PaceFrames(f(lo), f(pref), f(hi), f(DIALOGUE_MAX))


def target_frames(duration_s: int, rate: str) -> int:
    return round_fraction(Fraction(duration_s) * parse_rational(rate), Rounding.NEAREST)


def dominant_rate(assets: Iterable[tuple[str | None, int | None, str | None]]) -> str:
    """The source rate covering the most duration (``(rate, duration_ticks, tb)`` per
    video asset). High-frame-rate (≥ 100 fps) sources are conformed, so they never set
    the timeline rate; with nothing usable the default is 30000/1001."""
    totals: dict[Fraction, Fraction] = {}
    for rate, ticks, tb in assets:
        if not rate or not ticks or not tb:
            continue
        r = parse_rational(rate)
        if r <= 0 or r >= 100:
            continue
        totals[r] = totals.get(r, Fraction(0)) + Fraction(ticks) * parse_rational(tb)
    if not totals:
        return "30000/1001"
    best = max(totals.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return format_rational(best)
