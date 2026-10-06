"""Devices and clock correction helpers (M1 step 10a, ADR 0027)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mosaic.library.devices import (
    densest,
    describe,
    device_identity,
    format_offset,
    parse_offset,
    shift,
)


def test_parse_offset() -> None:
    assert parse_offset("+5h") == 5 * 3600 * 1000
    assert parse_offset("-1h30m") == -(90 * 60 * 1000)
    assert parse_offset("+90s") == 90_000
    assert parse_offset("-00:30:00") == -30 * 60 * 1000
    assert parse_offset("2:00") == 2 * 3600 * 1000
    assert parse_offset("+1500ms") == 1500
    for bad in ("", "soon", "5x", "+"):
        with pytest.raises(ValueError, match="offset"):
            parse_offset(bad)


def test_shift_keeps_offsets_and_naivety() -> None:
    assert shift("2025-03-01T23:00:00+00:00", 7_200_000) == "2025-03-02T01:00:00+00:00"
    assert shift("2025-03-01T23:00:00", -1500) == "2025-03-01T22:59:58.500"
    assert shift("2025-03-01T23:00:00+04:00", 0) == "2025-03-01T23:00:00+04:00"
    assert shift(None, 5) is None
    assert shift("garbage", 5) == "garbage"


def test_densest_cluster_and_wording() -> None:
    assert densest([10, 7_200_000, 7_201_000, 7_199_500, 50_000_000], 120_000) == [
        7_199_500,
        7_200_000,
        7_201_000,
    ]
    assert describe(7_200_000) == "2 h 00 m behind"
    assert describe(-12 * 60_000) == "12 min ahead"
    assert describe(30_000) == "on time"
    assert format_offset(-5_400_000) == "-1:30:00"


def test_device_identity() -> None:
    assert device_identity("Apple", "iPhone 15 Pro", None, "iphone") == (
        "Apple|iPhone 15 Pro|",
        "Apple iPhone 15 Pro",
    )
    assert device_identity(None, None, None, "gopro") == ("profile:gopro", "Gopro")
    assert device_identity(None, None, None, "generic")[1] == "Unknown camera"


@given(
    seconds=st.integers(0, 10**9),
    offset_ms=st.integers(-(10**9), 10**9),
    zone_min=st.sampled_from([-480, -60, 0, 60, 330, 540]),
)
def test_shift_round_trips(seconds: int, offset_ms: int, zone_min: int) -> None:
    tz = timezone(timedelta(minutes=zone_min))
    raw = (datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)).astimezone(tz)
    iso = raw.isoformat(timespec="seconds")
    there = shift(iso, offset_ms)
    assert there is not None
    assert shift(there, -offset_ms) == iso
    # Shown in another zone: the same instant.
    other = shift(iso, offset_ms, 120)
    assert other is not None
    assert datetime.fromisoformat(other) == datetime.fromisoformat(there)
    assert datetime.fromisoformat(other).utcoffset() == timedelta(minutes=120)


@given(st.integers(-7 * 86400, 7 * 86400))
def test_offset_text_round_trips(seconds: int) -> None:
    assert parse_offset(format_offset(seconds * 1000)) == seconds * 1000


@given(st.lists(st.integers(-(10**7), 10**7), min_size=1, max_size=40), st.integers(0, 10**6))
def test_densest_is_a_largest_window(xs: list[int], width: int) -> None:
    best = densest(xs, width)
    assert best
    assert max(best) - min(best) <= width
    for lo in xs:
        inside = [x for x in xs if lo <= x <= lo + width]
        assert len(inside) <= len(best)


def test_migration_keeps_existing_capture_times(tmp_path: object) -> None:
    from pathlib import Path

    from alembic import command
    from sqlalchemy import create_engine, text

    from mosaic.storage.db import alembic_config

    db = Path(str(tmp_path)) / "p.db"
    engine = create_engine(f"sqlite:///{db}")
    cfg = alembic_config("project")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "c92d4e1f7a38")
        conn.execute(
            text(
                "INSERT INTO provenance (id, kind, input_keys, tokens_in, tokens_out, cost_usd,"
                " created_at) VALUES (1, 'test', '[]', 0, 0, 0, 'now')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO asset (id, kind, status, profile, group_key, capture_time,"
                " provenance_id, created_at, hfr, vfr, rotation, color_hint, flags)"
                " VALUES (1, 'video', 'ok', 'gopro', 'g', '2025-03-01T23:00:00+00:00', 1,"
                " 'now', 0, 0, 0, 'sdr', '[]')"
            )
        )
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        row = conn.execute(text("SELECT capture_time, capture_time_raw FROM asset")).one()
    assert row == ("2025-03-01T23:00:00+00:00", "2025-03-01T23:00:00+00:00")
