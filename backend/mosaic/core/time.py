"""Exact time types (CLAUDE.md invariant 3, ARCHITECTURE.md §6).

Authoritative times are integers:

- ``SourceTime``: integer ticks in a stream time base, ``{"ticks": 4026240, "tb": "1/90000"}``.
- ``TimelineTime``: integer frames at a timeline rate, ``{"frames": 1724, "rate": "30000/1001"}``.

All conversions live here and use ``fractions.Fraction``. Float seconds exist only for
display or as transient values inside a function; ``from_float_seconds`` is the single
boundary where float timestamps produced by third-party libraries (for example Whisper)
become ticks.
"""

from __future__ import annotations

import math
from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, StrictInt

AUDIO_RATE = 48_000
"""Audio positions on the timeline are samples at 48 kHz (ARCHITECTURE.md §6)."""

DEFAULT_TB = Fraction(1, 90_000)

_NTSC_ALIASES: dict[str, Fraction] = {
    "23.976": Fraction(24000, 1001),
    "23.98": Fraction(24000, 1001),
    "29.97": Fraction(30000, 1001),
    "47.952": Fraction(48000, 1001),
    "59.94": Fraction(60000, 1001),
    "119.88": Fraction(120000, 1001),
}


class Rounding(StrEnum):
    FLOOR = "floor"
    CEIL = "ceil"
    NEAREST = "nearest"  # ties round half up (toward +inf), deterministic
    EXACT = "exact"  # raise if the value is not representable


class InexactTimeError(ValueError):
    """Raised by ``Rounding.EXACT`` when a conversion would lose precision."""


def parse_rational(value: Any) -> Fraction:
    """Parse ``"30000/1001"``, ``"1/90000"``, ``"29.97"``, ``"25"``, ints or Fractions.

    NTSC decimal aliases map to their exact rationals. Floats are rejected: a rate or a
    time base must never travel as a float.
    """
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, bool):
        raise TypeError("rational value cannot be a bool")
    elif isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, str):
        text = value.strip()
        if "." in text and "/" not in text:
            text = text.rstrip("0").rstrip(".") or "0"
        if text in _NTSC_ALIASES:
            result = _NTSC_ALIASES[text]
        elif "/" in text:
            num, den = text.split("/", 1)
            result = Fraction(int(num), int(den))
        else:
            result = Fraction(text)
    else:
        raise TypeError(f"expected a rational string, int or Fraction, got {type(value).__name__}")
    if result <= 0:
        raise ValueError(f"rational must be positive, got {result}")
    return result


def format_rational(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


Rational = Annotated[
    Fraction,
    BeforeValidator(parse_rational),
    PlainSerializer(format_rational, return_type=str),
]
"""A positive exact rational, serialized as ``"num/den"``."""


def round_fraction(value: Fraction, rounding: Rounding) -> int:
    if rounding is Rounding.FLOOR:
        return math.floor(value)
    if rounding is Rounding.CEIL:
        return math.ceil(value)
    if rounding is Rounding.NEAREST:
        return math.floor(value + Fraction(1, 2))
    if value.denominator != 1:
        raise InexactTimeError(f"{value} is not an integer")
    return value.numerator


class SourceTime(BaseModel):
    """Integer ticks in a stream time base, relative to the stream's first PTS.

    ``==`` compares fields (ticks and time base); ``<``/``<=``/``>``/``>=`` compare instants
    across time bases. Use ``same_instant`` for instant equality.
    """

    model_config = ConfigDict(frozen=True, strict=False, extra="forbid")

    ticks: StrictInt
    tb: Rational

    @classmethod
    def of(cls, ticks: int, tb: Fraction | str = DEFAULT_TB) -> SourceTime:
        return cls(ticks=ticks, tb=parse_rational(tb))

    @classmethod
    def from_seconds(
        cls, seconds: Fraction, tb: Fraction | str, rounding: Rounding = Rounding.NEAREST
    ) -> SourceTime:
        tb_f = parse_rational(tb)
        return cls(ticks=round_fraction(seconds / tb_f, rounding), tb=tb_f)

    @classmethod
    def from_float_seconds(
        cls, seconds: float, tb: Fraction | str, rounding: Rounding = Rounding.NEAREST
    ) -> SourceTime:
        """Boundary conversion for float timestamps from third-party libraries."""
        if not math.isfinite(seconds):
            raise ValueError(f"non-finite seconds: {seconds}")
        return cls.from_seconds(Fraction(repr(seconds)), tb, rounding)

    @property
    def seconds(self) -> Fraction:
        """Exact seconds, for transient computation only."""
        return self.ticks * self.tb

    def rescale(self, tb: Fraction | str, rounding: Rounding = Rounding.NEAREST) -> SourceTime:
        tb_f = parse_rational(tb)
        if tb_f == self.tb:
            return self
        return SourceTime(ticks=round_fraction(self.seconds / tb_f, rounding), tb=tb_f)

    def to_frames(self, rate: Fraction | str, rounding: Rounding = Rounding.NEAREST) -> int:
        """Index of the frame at ``rate`` that contains (FLOOR) or is nearest to this time."""
        return round_fraction(self.seconds * parse_rational(rate), rounding)

    def to_samples(self, rate: int = AUDIO_RATE, rounding: Rounding = Rounding.NEAREST) -> int:
        return round_fraction(self.seconds * rate, rounding)

    def plus_ticks(self, ticks: int) -> SourceTime:
        return SourceTime(ticks=self.ticks + ticks, tb=self.tb)

    def plus(self, other: SourceTime) -> SourceTime:
        return SourceTime(ticks=self.ticks + _ticks_in(other, self.tb), tb=self.tb)

    def minus(self, other: SourceTime) -> SourceTime:
        return SourceTime(ticks=self.ticks - _ticks_in(other, self.tb), tb=self.tb)

    def _key(self) -> Fraction:
        return self.seconds

    def __lt__(self, other: SourceTime) -> bool:
        return self._key() < other._key()

    def __le__(self, other: SourceTime) -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: SourceTime) -> bool:
        return self._key() > other._key()

    def __ge__(self, other: SourceTime) -> bool:
        return self._key() >= other._key()

    def same_instant(self, other: SourceTime) -> bool:
        return self._key() == other._key()

    def display(self) -> str:
        return format_display(self.seconds)


def _ticks_in(value: SourceTime, tb: Fraction) -> int:
    """Exact ticks of ``value`` in ``tb``; raises if not representable."""
    return round_fraction(value.seconds / tb, Rounding.EXACT)


class TimelineTime(BaseModel):
    """Integer frames at the timeline rate."""

    model_config = ConfigDict(frozen=True, strict=False, extra="forbid")

    frames: StrictInt
    rate: Rational

    @classmethod
    def of(cls, frames: int, rate: Fraction | str) -> TimelineTime:
        return cls(frames=frames, rate=parse_rational(rate))

    @property
    def seconds(self) -> Fraction:
        """Exact seconds, for transient computation only."""
        return self.frames / self.rate

    def to_source(self, tb: Fraction | str, rounding: Rounding = Rounding.NEAREST) -> SourceTime:
        return SourceTime.from_seconds(self.seconds, tb, rounding)

    def to_samples(self, rate: int = AUDIO_RATE, rounding: Rounding = Rounding.NEAREST) -> int:
        return round_fraction(self.seconds * rate, rounding)

    def plus_frames(self, frames: int) -> TimelineTime:
        return TimelineTime(frames=self.frames + frames, rate=self.rate)

    def display(self) -> str:
        return format_display(self.seconds)


class SourceRange(BaseModel):
    """Half-open range ``[start, end)`` in one time base."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: SourceTime
    end: SourceTime

    def model_post_init(self, __context: Any) -> None:
        if self.start.tb != self.end.tb:
            raise ValueError("range endpoints must share a time base")
        if self.end.ticks < self.start.ticks:
            raise ValueError("range end precedes start")

    @classmethod
    def of(cls, start: int, end: int, tb: Fraction | str = DEFAULT_TB) -> SourceRange:
        tb_f = parse_rational(tb)
        return cls(start=SourceTime(ticks=start, tb=tb_f), end=SourceTime(ticks=end, tb=tb_f))

    @property
    def tb(self) -> Fraction:
        return self.start.tb

    @property
    def duration_ticks(self) -> int:
        return self.end.ticks - self.start.ticks

    @property
    def duration_seconds(self) -> Fraction:
        """Exact seconds, for transient computation only."""
        return self.duration_ticks * self.tb

    def contains(self, t: SourceTime) -> bool:
        return self.start <= t < self.end

    def intersect(self, other: SourceRange) -> SourceRange | None:
        o = other.rescale(self.tb, Rounding.NEAREST)
        start = max(self.start.ticks, o.start.ticks)
        end = min(self.end.ticks, o.end.ticks)
        if end <= start:
            return None
        return SourceRange.of(start, end, self.tb)

    def rescale(self, tb: Fraction | str, rounding: Rounding = Rounding.NEAREST) -> SourceRange:
        return SourceRange(
            start=self.start.rescale(tb, rounding), end=self.end.rescale(tb, rounding)
        )


def timeline_frames_for_duration(
    seconds: Fraction, rate: Fraction | str, rounding: Rounding = Rounding.NEAREST
) -> int:
    return round_fraction(seconds * parse_rational(rate), rounding)


def frame_start_ticks(frame: int, rate: Fraction | str, tb: Fraction | str) -> int:
    """First tick (ceil) at or after the start of ``frame`` at ``rate``."""
    return round_fraction(
        Fraction(frame) / parse_rational(rate) / parse_rational(tb), Rounding.CEIL
    )


def format_display(seconds: Fraction) -> str:
    """``mm:ss.t`` (or ``h:mm:ss.t``) for display only; truncates to tenths."""
    sign = "-" if seconds < 0 else ""
    tenths = math.floor(abs(seconds) * 10)
    total_s, t = divmod(tenths, 10)
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{sign}{h}:{m:02d}:{s:02d}.{t}"
    return f"{sign}{m:02d}:{s:02d}.{t}"
