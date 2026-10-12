"""Version compare (S18, ADR 0083): what changed between two versions' shots, matched by
the storyboard refs that stay with a shot."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.editing.versions import diff


def _ev(ref: str, seg: str, at: int, src: int = 0) -> dict[str, Any]:
    return {
        "event_id": f"evt_{at:04d}",
        "segment_id": seg,
        "source_in": {"ticks": src, "tb": "1/1000"},
        "source_out": {"ticks": src + 3000, "tb": "1/1000"},
        "timeline_in": {"frames": at * 90, "rate": "30/1"},
        "origin": {"selection_ref": ref},
    }


def test_each_kind_of_change() -> None:
    a = [_ev("b1#0", "seg_1", 0), _ev("b1#1", "seg_2", 1), _ev("b1#2", "seg_3", 2),
         _ev("b2#0", "seg_4", 3), _ev("b2#1", "seg_5", 4)]  # fmt: skip
    b = [
        _ev("b1#0", "seg_1", 0),
        _ev("b2#0", "seg_4", 1),  # moved ahead of b1#1
        _ev("b1#1", "seg_9", 2),  # replaced
        _ev("b2#1", "seg_5", 3, src=500),  # trimmed
        _ev("b3#0", "seg_7", 4),  # added
    ]  # b1#2 removed
    changes = diff(a, b, 1, 2)
    got = {(c["kind"], c["ref"]) for c in changes}
    assert got >= {
        ("replaced", "b1#1"),
        ("trimmed", "b2#1"),
        ("added", "b3#0"),
        ("removed", "b1#2"),
    }
    # b1#0 and b2#1 keep their order; one of the swapped pair is marked moved.
    assert [c["ref"] for c in changes if c["moved"]] in (["b2#0"], ["b1#1"])
    assert "b1#0" not in {c["ref"] for c in changes}
    removed = diff(a, b, 1, 2)[-1]
    assert removed["in_version"] == 1
    assert removed["frame"] == 180, "where it was"
    assert diff(a, a, 1, 1) == []


@settings(max_examples=100, deadline=None)
@given(st.permutations(list(range(6))), st.sets(st.integers(0, 5), max_size=3))
def test_a_reorder_marks_only_shots_outside_the_kept_order(
    order: list[int], drop: set[int]
) -> None:
    a = [_ev(f"r{i}", f"s{i}", i) for i in range(6)]
    b = [_ev(f"r{i}", f"s{i}", k) for k, i in enumerate(i for i in order if i not in drop)]
    changes = diff(a, b, 1, 2)
    assert {c["ref"] for c in changes if c["kind"] == "removed"} == {f"r{i}" for i in drop}
    moved = [int(c["ref"][1:]) for c in changes if c["moved"]]
    kept = [i for i in order if i not in drop and i not in moved]
    assert kept == sorted(kept), "what is not marked moved keeps its order"
    assert all(c["kind"] in ("moved", "removed") for c in changes)
