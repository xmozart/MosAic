"""Storyboard ops (S16; ADR 0067): each changes the storyboard and nothing else, refuses
what does not fit, and never touches a locked shot."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mosaic.editing.draft import OP, Board, DraftError, apply


def _board() -> Board:
    def shot(ref: str, seg: str, alts: list[str] | None = None) -> dict[str, object]:
        return {
            "ref": ref,
            "segment_id": seg,
            "role": "b_roll",
            "priority": 3,
            "length": "medium",
            "audio_intent": "natural_sound",
            "reason": "Picked",
            "alternatives": [{"segment_id": a, "why_not": "Softer"} for a in alts or []],
        }

    return Board.model_validate(
        {
            "title": "Trip",
            "beats": [
                {
                    "beat_id": "b1",
                    "title": "Arrival",
                    "intent": "Arrive",
                    "share_percent": 50,
                    "pool": ["seg_000001", "seg_000002", "seg_000003", "seg_000009"],
                    "shots": [
                        shot("b1#0", "seg_000001", ["seg_000003"]),
                        shot("b1#1", "seg_000002"),
                    ],
                },
                {
                    "beat_id": "b2",
                    "title": "The reef",
                    "intent": "Dive",
                    "share_percent": 50,
                    "pool": ["seg_000004", "seg_000005"],
                    "shots": [shot("b2#0", "seg_000004"), shot("b2#1", "seg_000005")],
                },
            ],
        }
    )


def _refs(b: Board) -> list[list[str]]:
    return [[s.ref for s in beat.shots] for beat in b.beats]


def test_moving_a_shot_keeps_its_ref_and_takes_the_owners_order() -> None:
    board = _board()
    moved = apply(
        board, OP.validate_python({"kind": "move_shot", "ref": "b1#0", "beat_id": "b2", "index": 1})
    )
    assert _refs(moved) == [["b1#1"], ["b2#0", "b1#0", "b2#1"]]
    assert moved.user_order
    assert not board.user_order
    assert _refs(board) == [["b1#0", "b1#1"], ["b2#0", "b2#1"]]
    end = apply(
        board,
        OP.validate_python({"kind": "move_shot", "ref": "b2#1", "beat_id": "b1", "index": 99}),
    )
    assert _refs(end) == [["b1#0", "b1#1", "b2#1"], ["b2#0"]]


def test_moving_a_beat() -> None:
    moved = apply(_board(), OP.validate_python({"kind": "move_beat", "beat_id": "b2", "index": 0}))
    assert [b.beat_id for b in moved.beats] == ["b2", "b1"]
    assert moved.user_order


def test_a_locked_shot_cannot_be_removed_or_replaced() -> None:
    locked = apply(_board(), OP.validate_python({"kind": "lock_shot", "ref": "b1#0"}))
    assert locked.shot("b1#0")[2].locked
    with pytest.raises(DraftError, match="locked"):
        apply(locked, OP.validate_python({"kind": "remove_shot", "ref": "b1#0"}))
    with pytest.raises(DraftError, match="locked"):
        apply(
            locked,
            OP.validate_python({"kind": "replace_shot", "ref": "b1#0", "segment_id": "seg_000003"}),
        )
    unlocked = apply(
        locked, OP.validate_python({"kind": "lock_shot", "ref": "b1#0", "locked": False})
    )
    removed = apply(unlocked, OP.validate_python({"kind": "remove_shot", "ref": "b1#0"}))
    assert _refs(removed) == [["b1#1"], ["b2#0", "b2#1"]]
    assert not removed.user_order, "removing keeps the chronology's order"


def test_replacing_from_alternatives_or_the_pool() -> None:
    board = _board()
    alt = apply(
        board,
        OP.validate_python({"kind": "replace_shot", "ref": "b1#0", "segment_id": "seg_000003"}),
    )
    _, _, sh = alt.shot("b1#0")
    assert sh.segment_id == "seg_000003"
    assert sh.alternatives[0] == {"segment_id": "seg_000001", "why_not": "Replaced by you"}
    assert all(a["segment_id"] != "seg_000003" for a in sh.alternatives)
    pool = apply(
        board,
        OP.validate_python({"kind": "replace_shot", "ref": "b1#1", "segment_id": "seg_000009"}),
    )
    assert pool.shot("b1#1")[2].segment_id == "seg_000009"
    with pytest.raises(DraftError, match="not an alternative"):
        apply(
            board,
            OP.validate_python({"kind": "replace_shot", "ref": "b1#1", "segment_id": "seg_000004"}),
        )
    with pytest.raises(DraftError, match="already in this edit"):
        apply(
            board,
            OP.validate_python({"kind": "replace_shot", "ref": "b1#0", "segment_id": "seg_000002"}),
        )


def test_unknown_shots_beats_and_ops_are_refused() -> None:
    with pytest.raises(DraftError):
        apply(_board(), OP.validate_python({"kind": "remove_shot", "ref": "b9#0"}))
    with pytest.raises(DraftError):
        apply(
            _board(),
            OP.validate_python({"kind": "move_shot", "ref": "b1#0", "beat_id": "b9", "index": 0}),
        )
    with pytest.raises(ValidationError, match="does not match any of the expected tags"):
        OP.validate_python({"kind": "trim", "ref": "b1#0"})
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        OP.validate_python({"kind": "move_beat", "beat_id": "b1", "index": -1})


def test_locking_a_cut_of_two_picks_absorbs_the_second() -> None:
    pin = {
        "segment_id": "seg_000001",
        "source_in": {"ticks": 0, "tb": "1/1000"},
        "source_out": {"ticks": 9000, "tb": "1/1000"},
        "duration": {"frames": 270, "rate": "30/1"},
    }
    locked = apply(
        _board(),
        OP.validate_python({"kind": "lock_shot", "ref": "b1#0", "pin": pin, "absorb": ["b1#1"]}),
    )
    first, second = locked.shot("b1#0")[2], locked.shot("b1#1")[2]
    assert first.locked
    assert first.pin is not None
    assert first.pin.duration.frames == 270
    assert second.absorbed_by == "b1#0"
    with pytest.raises(DraftError, match="locked"):
        apply(locked, OP.validate_python({"kind": "remove_shot", "ref": "b1#1"}))
    with pytest.raises(DraftError, match="part of b1#0"):
        apply(locked, OP.validate_python({"kind": "lock_shot", "ref": "b1#1", "locked": False}))
    released = apply(
        locked, OP.validate_python({"kind": "lock_shot", "ref": "b1#0", "locked": False})
    )
    assert released.shot("b1#0")[2].pin is None
    assert released.shot("b1#1")[2].absorbed_by is None

    with pytest.raises(DraftError, match="part of b1#0"):
        apply(
            locked,
            OP.validate_python({"kind": "move_shot", "ref": "b1#1", "beat_id": "b2", "index": 0}),
        )
    other = {**pin, "segment_id": "seg_000002"}
    with pytest.raises(DraftError, match="changed since it was timed"):
        apply(_board(), OP.validate_python({"kind": "lock_shot", "ref": "b1#0", "pin": other}))
    backwards = {**pin, "source_out": {"ticks": 0, "tb": "1/1000"}}
    with pytest.raises(ValidationError, match="out point is after its in point"):
        OP.validate_python({"kind": "lock_shot", "ref": "b1#0", "pin": backwards})
    mixed = {**pin, "source_out": {"ticks": 9000, "tb": "1/90000"}}
    with pytest.raises(ValidationError, match="share one time base"):
        OP.validate_python({"kind": "lock_shot", "ref": "b1#0", "pin": mixed})
