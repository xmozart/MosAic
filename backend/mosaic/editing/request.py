"""The edit request (PRODUCT.md §4), pace in frames, and the timeline rate (M0 defaults)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mosaic.core.time import Rounding, format_rational, parse_rational, round_fraction

Chronology = Literal["strict", "mostly", "thematic", "story"]
Arc = Literal["classic_travel", "fast_highlight", "documentary", "custom"]
# Content weights (PRODUCT.md §4): a category left out is neutral.
Weight = Literal["avoid", "less", "neutral", "more", "strong"]
Category = Literal[
    "people",
    "reactions",
    "landscapes",
    "wildlife",
    "architecture",
    "food",
    "culture",
    "action",
    "drone",
    "pov",
    "selfies",
    "conversations",
    "natural_sound",
    "humor",
    "transport",
    "sunsets",
    "water",
    "night",
    "city",
    "slow_motion",
    "timelapse",
    "photos",
]
PhotoShare = Literal["none", "some", "many"]
Transitions = Literal["cuts", "dissolves", "minimal"]
Loudness = Literal["web", "tv"]
# The output's shape and the final render's size (PRODUCT.md §4 Destination; ADR 0046).
Aspect = Literal["16:9", "9:16", "4:5", "1:1", "2.39:1"]
Resolution = Literal["720p", "1080p", "1440p", "4k"]
# Fields that change only how an edit is rendered, never which shots it picks: they are
# not part of the edit's key, so changing them re-renders without re-planning.
RENDER_ONLY = frozenset({"aspect", "resolution", "loudness"})
# Added in M4 (ADR 0066): left out of the key while at their defaults.
M4_FIELDS = (
    "arc",
    "beats",
    "weights",
    "rules",
    "photo_share",
    "shot_lengths",
    "transitions",
    "audio",
    "music",
)
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


class Rules(BaseModel):
    """Editing rules (PRODUCT.md §4); the defaults are the wizard's."""

    model_config = ConfigDict(extra="forbid")

    avoid_repetition: bool = True
    allow_imperfect: bool = False  # imperfect but emotional clips
    unique_over_quality: bool = True  # unique moments over technical quality
    drone_openers: bool = False
    remove_dead_time: bool = False  # aggressively
    long_holds: bool = False  # long cinematic holds


class ShotLengths(BaseModel):
    """Advanced pace (PRODUCT.md §4): min, preferred and max shot length in tenths of a
    second, as the user enters them (integers: invariant 3)."""

    model_config = ConfigDict(extra="forbid")

    min_ds: int = Field(ge=3, le=600)
    preferred_ds: int = Field(ge=3, le=600)
    max_ds: int = Field(ge=3, le=1200)

    @model_validator(mode="after")
    def _ordered(self) -> ShotLengths:
        if not self.min_ds <= self.preferred_ds <= self.max_ds:
            raise ValueError("shot lengths must be min ≤ preferred ≤ max")
        return self


class Audio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_dialogue: bool = True  # never cut someone mid-sentence
    natural_sound: bool = True
    reduce_wind: bool = True


class Music(BaseModel):
    """A user track laid under the edit with fades and a static level (v1; beat
    awareness is M6). ``path`` is the track's absolute path; it is read, never changed."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    level_db: int = Field(default=-18, ge=-40, le=0)  # under the edit's own sound
    fade_in_ms: int = Field(default=2000, ge=0, le=10_000)
    fade_out_ms: int = Field(default=3000, ge=0, le=10_000)


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
    aspect: Aspect = "16:9"
    resolution: Resolution = "1080p"  # the final render's short side; previews are 720p
    # M4 (PRODUCT.md §4; ADR 0066). Every field has the wizard's default, so requests
    # saved before M4 load unchanged.
    arc: Arc = "classic_travel"
    beats: list[str] = Field(default_factory=list, max_length=12)  # custom arc, in order
    weights: dict[Category, Weight] = Field(default_factory=dict)
    rules: Rules = Field(default_factory=Rules)
    photo_share: PhotoShare = "some"
    shot_lengths: ShotLengths | None = None  # None: the pace's own
    transitions: Transitions = "cuts"
    audio: Audio = Field(default_factory=Audio)
    loudness: Loudness = "web"
    music: Music | None = None

    def key_dump(self) -> dict[str, object]:
        """What the edit's key hashes: everything but the render-only fields. Fields added
        in M4 count only when they differ from their default, so a request saved before
        M4 keeps its key (invariant 9; ADR 0066)."""
        out = self.model_dump(mode="json", exclude=set(RENDER_ONLY))
        for name in M4_FIELDS:
            if getattr(self, name) == type(self).model_fields[name].get_default(
                call_default_factory=True
            ):
                out.pop(name, None)
        return out

    @field_validator("story")
    @classmethod
    def _story(cls, v: str) -> str:
        if v not in STORY_PRESETS:
            raise ValueError(f"unknown story {v!r}; choose one of {', '.join(STORY_PRESETS)}")
        return v

    @field_validator("beats")
    @classmethod
    def _beats(cls, v: list[str]) -> list[str]:
        beats = [b.strip() for b in v]
        if any(not b or len(b) > 80 for b in beats):
            raise ValueError("each beat is 1–80 characters")
        return beats

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[Category, Weight]) -> dict[Category, Weight]:
        # Neutral is the default: leaving it out keeps one request one key.
        return {k: w for k, w in sorted(v.items()) if w != "neutral"}

    @model_validator(mode="after")
    def _arc(self) -> EditRequest:
        if self.arc == "custom" and not self.beats:
            raise ValueError("a custom arc needs at least one beat")
        if self.arc != "custom" and self.beats:
            raise ValueError("beats are for a custom arc")
        return self

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


def pace_frames(pace: str, rate: str, lengths: ShotLengths | None = None) -> PaceFrames:
    """The pace's shot lengths in frames; ``lengths`` (Advanced) replaces them."""
    lo, pref, hi = PACE_SECONDS[pace]
    if lengths is not None:
        lo, pref, hi = (
            Fraction(lengths.min_ds, 10),
            Fraction(lengths.preferred_ds, 10),
            Fraction(lengths.max_ds, 10),
        )
    r = parse_rational(rate)

    def f(s: Fraction) -> int:
        return round_fraction(s * r, Rounding.NEAREST)

    # Dialogue may always run at least as long as any other shot (PRODUCT.md §4).
    return PaceFrames(f(lo), f(pref), f(hi), f(max(DIALOGUE_MAX, hi)))


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
