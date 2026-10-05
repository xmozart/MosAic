"""Hierarchical summaries (M1 step 5): composition, bounds and validation helpers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from mosaic.library.summaries import (
    MAX_DAY_ITEMS,
    _compose,
    check_highlights,
    day_items,
    day_label,
)


def _seg(i: int, start: int) -> Any:
    return SimpleNamespace(id=i, start_ticks=start, shot_id=1)


def test_compose_prefers_interesting_clips_in_time_order() -> None:
    segs = [_seg(1, 0), _seg(2, 10), _seg(3, 20), _seg(4, 30), _seg(5, 40)]
    obs = {
        1: {"description": "Crowd on the pier.", "subjects": ["crowd"], "interest": "low"},
        2: {"description": "Jet climbs.", "subjects": ["jet", "sky"], "interest": "high"},
        3: {"description": "Jet rolls.", "subjects": ["jet"], "interest": "high"},
        4: {"description": "Boats.", "subjects": ["boat"], "interest": "medium"},
    }
    part = _compose(segs, obs)
    assert part is not None
    assert part["text"] == "Jet climbs. Jet rolls. Boats."
    assert part["subjects"][0] == "jet"
    assert part["highlights"] == ["seg_000002", "seg_000003", "seg_000004"]
    assert part["interest"] == 3
    assert _compose([_seg(5, 40)], obs) is None  # no observation, no summary


def test_day_items_keep_the_most_interesting_in_time_order() -> None:
    entries = [(f"line {i}", 3 if i % 7 == 0 else 1) for i in range(MAX_DAY_ITEMS + 20)]
    text = day_items(entries)
    lines = text.splitlines()
    assert len(lines) == MAX_DAY_ITEMS
    nums = [int(x.split()[1]) for x in lines]
    assert nums == sorted(nums)
    assert all(f"line {i}" in lines for i in range(0, MAX_DAY_ITEMS + 20, 7))


def test_highlights_must_come_from_the_notes() -> None:
    items = "10:00 · ast_0001 · 0:30: Jet. Clips: seg_000002 (Jet climbs)"
    ok = SimpleNamespace(highlights=["seg_000002"])
    bad = SimpleNamespace(highlights=["seg_000002", "seg_000009"])
    assert check_highlights(ok, items) == []
    assert "seg_000009" in check_highlights(bad, items)[0]
    twice = SimpleNamespace(highlights=["seg_000002", "seg_000002"])
    assert "once" in check_highlights(twice, items)[0]


def test_day_labels() -> None:
    assert day_label(2, date(2026, 9, 5)) == "day 2 (2026-09-06)"
    assert day_label(0, date(2026, 9, 5)) == "the recordings without a date"
    assert day_label(1, None) == "the recordings without a date"
