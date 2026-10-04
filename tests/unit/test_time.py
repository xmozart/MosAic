from __future__ import annotations

import json
from fractions import Fraction

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from mosaic.core.time import (
    InexactTimeError,
    Rounding,
    SourceRange,
    SourceTime,
    TimelineTime,
    format_display,
    frame_start_ticks,
    parse_rational,
    round_fraction,
    timeline_frames_for_duration,
)

TBS = st.sampled_from(
    [
        Fraction(1, 90000),
        Fraction(1, 48000),
        Fraction(1, 30000),
        Fraction(1, 600),
        Fraction(1, 1000),
        Fraction(1001, 30000),
        Fraction(1, 15360),
        Fraction(1, 44100),
    ]
)
RATES = st.sampled_from(
    [
        Fraction(24000, 1001),
        Fraction(24),
        Fraction(25),
        Fraction(30000, 1001),
        Fraction(30),
        Fraction(50),
        Fraction(60000, 1001),
        Fraction(60),
        Fraction(120),
    ]
)
TICKS = st.integers(min_value=-(10**12), max_value=10**12)


def test_json_shape_matches_spec() -> None:
    t = SourceTime.of(4026240, "1/90000")
    assert json.loads(t.model_dump_json()) == {"ticks": 4026240, "tb": "1/90000"}
    tt = TimelineTime.of(1724, "30000/1001")
    assert json.loads(tt.model_dump_json()) == {"frames": 1724, "rate": "30000/1001"}
    assert SourceTime.model_validate({"ticks": 5, "tb": "1/90000"}) == SourceTime.of(5)


def test_parse_rational_aliases_and_rejects_float() -> None:
    assert parse_rational("29.97") == Fraction(30000, 1001)
    assert parse_rational("59.94") == Fraction(60000, 1001)
    assert parse_rational("25") == 25
    with pytest.raises(TypeError):
        parse_rational(29.97)
    with pytest.raises(ValueError, match="positive"):
        parse_rational("0/1")


@given(TICKS, TBS)
def test_rescale_round_trip_through_finer_base_is_exact(ticks: int, tb: Fraction) -> None:
    finer = tb / 7
    t = SourceTime(ticks=ticks, tb=tb)
    assert t.rescale(finer, Rounding.EXACT).rescale(tb, Rounding.EXACT) == t


@given(TICKS, TBS, TBS)
def test_rescale_error_bounded_by_half_tick(ticks: int, tb_a: Fraction, tb_b: Fraction) -> None:
    t = SourceTime(ticks=ticks, tb=tb_a)
    r = t.rescale(tb_b, Rounding.NEAREST)
    assert abs(r.seconds - t.seconds) <= tb_b / 2


@given(TICKS, TBS, TBS)
def test_floor_ceil_bracket(ticks: int, tb_a: Fraction, tb_b: Fraction) -> None:
    t = SourceTime(ticks=ticks, tb=tb_a)
    lo = t.rescale(tb_b, Rounding.FLOOR)
    hi = t.rescale(tb_b, Rounding.CEIL)
    assert lo.seconds <= t.seconds <= hi.seconds
    assert hi.ticks - lo.ticks in (0, 1)


@given(st.integers(min_value=-(10**9), max_value=10**9), RATES, TBS)
def test_frame_to_source_and_back_nearest(frames: int, rate: Fraction, tb: Fraction) -> None:
    # Any tick base finer than half a frame round-trips frame indices exactly.
    assume(tb < 1 / (2 * rate))
    tt = TimelineTime(frames=frames, rate=rate)
    assert tt.to_source(tb).to_frames(rate, Rounding.NEAREST) == frames


@given(TICKS, TBS, RATES)
def test_to_frames_floor_contains_time(ticks: int, tb: Fraction, rate: Fraction) -> None:
    t = SourceTime(ticks=ticks, tb=tb)
    f = t.to_frames(rate, Rounding.FLOOR)
    assert Fraction(f) / rate <= t.seconds < Fraction(f + 1) / rate


@given(TICKS, TICKS, TBS)
def test_plus_minus_inverse(a: int, b: int, tb: Fraction) -> None:
    x = SourceTime(ticks=a, tb=tb)
    y = SourceTime(ticks=b, tb=tb)
    assert x.plus(y).minus(y) == x


@given(TICKS, TBS)
def test_ordering_consistent_with_seconds(ticks: int, tb: Fraction) -> None:
    x = SourceTime(ticks=ticks, tb=tb)
    y = x.rescale(tb / 3, Rounding.EXACT).plus_ticks(1)
    assert x < y
    assert y > x
    assert x.same_instant(x.rescale(tb / 2, Rounding.EXACT))


@given(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False), TBS)
def test_from_float_seconds_is_within_half_tick(seconds: float, tb: Fraction) -> None:
    t = SourceTime.from_float_seconds(seconds, tb)
    assert abs(t.seconds - Fraction(repr(seconds))) <= tb / 2
    assert isinstance(t.ticks, int)


def test_from_float_rejects_nan() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        SourceTime.from_float_seconds(float("nan"), "1/90000")


def test_exact_rounding_raises() -> None:
    with pytest.raises(InexactTimeError):
        round_fraction(Fraction(1, 3), Rounding.EXACT)


@given(st.fractions(min_value=-100, max_value=100))
def test_nearest_rounding_ties_up(x: Fraction) -> None:
    n = round_fraction(x, Rounding.NEAREST)
    assert abs(Fraction(n) - x) <= Fraction(1, 2)
    if x - int(x) == Fraction(1, 2) and x > 0:
        assert n == int(x) + 1


def test_range_ops() -> None:
    r = SourceRange.of(100, 200)
    assert r.duration_ticks == 100
    assert r.contains(SourceTime.of(100))
    assert not r.contains(SourceTime.of(200))
    assert r.intersect(SourceRange.of(150, 300)) == SourceRange.of(150, 200)
    assert r.intersect(SourceRange.of(200, 300)) is None
    with pytest.raises(ValueError, match="precedes"):
        SourceRange.of(5, 1)


def test_display() -> None:
    assert format_display(Fraction(1343, 10)) == "02:14.3"
    assert format_display(Fraction(3723)) == "1:02:03.0"
    assert SourceTime.of(90000 * 61 + 45000).display() == "01:01.5"


def test_float_and_string_ticks_are_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SourceTime.model_validate({"ticks": 4.0, "tb": "1/90000"})
    with pytest.raises(ValidationError):
        TimelineTime.model_validate({"frames": "7", "rate": "25"})


def test_decimal_rate_normalization() -> None:
    assert parse_rational("29.970") == Fraction(30000, 1001)
    assert parse_rational("25.0") == 25


@given(st.integers(min_value=0, max_value=10**7), RATES, TBS)
def test_frame_start_ticks_is_first_tick_in_frame(frame: int, rate: Fraction, tb: Fraction) -> None:
    t = frame_start_ticks(frame, rate, tb)
    assert t * tb >= Fraction(frame) / rate
    assert (t - 1) * tb < Fraction(frame) / rate


@given(st.fractions(min_value=0, max_value=10**5), RATES)
def test_timeline_frames_for_duration_nearest(seconds: Fraction, rate: Fraction) -> None:
    n = timeline_frames_for_duration(seconds, rate)
    assert abs(Fraction(n) / rate - seconds) <= 1 / (2 * rate)


@given(
    st.fractions(min_value=0, max_value=10**5),
    st.floats(min_value=0, max_value=1e5, allow_nan=False),
    TBS,
)
def test_from_float_offset_is_integer_and_within_half_tick(
    base: Fraction, seconds: float, tb: Fraction
) -> None:
    t = SourceTime.from_float_offset(base, seconds, tb)
    assert isinstance(t.ticks, int)
    assert abs(t.seconds - (base + Fraction(repr(seconds)))) <= tb / 2


def test_from_float_offset_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        SourceTime.from_float_offset(Fraction(0), float("inf"), "1/90000")
