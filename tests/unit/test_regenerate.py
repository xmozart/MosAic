"""Regenerating one beat (ADR 0069): the slots, the answer's checks and how new picks
fill the free slots around the locked shots."""

from __future__ import annotations

from typing import Any

import pytest

from mosaic.ai.prompts.reselect.schema_v1 import Output as ReselectOut
from mosaic.editing import regenerate
from mosaic.editing.draft import Board, DraftError
from mosaic.editing.retrieval import Candidate


def _pick(
    ref: str, seg: str, *, locked: bool = False, absorbed: str | None = None
) -> dict[str, Any]:
    return {
        "ref": ref,
        "segment_id": seg,
        "role": "b_roll",
        "priority": 3,
        "length": "medium",
        "audio_intent": "natural_sound",
        "reason": "Picked",
        "locked": locked,
        "absorbed_by": absorbed,
    }


def _board() -> Board:
    return Board.model_validate(
        {
            "title": "Trip",
            "excluded": ["seg_000099"],
            "beats": [
                {
                    "beat_id": "b1",
                    "title": "Arrival",
                    "intent": "Arrive",
                    "share_percent": 60,
                    "pool": [f"seg_{n:06d}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 99)],
                    "shots": [
                        _pick("b1#0", "seg_000001", locked=True),
                        _pick("b1#1", "seg_000002"),
                        _pick("b1#2", "seg_000003"),
                        _pick("b1#3", "seg_000004", locked=True),
                        _pick("b1#4", "seg_000005", absorbed="b1#3"),
                        _pick("b1#5", "seg_000006"),
                    ],
                },
                {
                    "beat_id": "b2",
                    "title": "Home",
                    "intent": "Leave",
                    "share_percent": 40,
                    "pool": ["seg_000007", "seg_000010"],
                    "shots": [_pick("b2#0", "seg_000007")],
                },
            ],
        }
    )


def _answer(*segs: str, beat: str = "b1") -> ReselectOut:
    return ReselectOut.model_validate(
        {
            "beat_id": beat,
            "selections": [
                {
                    "segment_id": s,
                    "role": "b_roll",
                    "priority": 3,
                    "length": "medium",
                    "audio_intent": "natural_sound",
                    "reason": "Fresh",
                    "alternatives": [],
                }
                for s in segs
            ],
        }
    )


def test_slots_keep_locked_and_absorbed_shots_fixed() -> None:
    sl = regenerate.slots(_board(), "b1")
    assert sorted(sl.fixed) == [0, 3, 4]
    assert sl.free == 3
    assert sl.needed == 2, "two free slots lie before the last fixed one"
    assert regenerate.avoid(_board(), "b1") == {"seg_000007", "seg_000099"}
    with pytest.raises(DraftError, match="no beat"):
        regenerate.slots(_board(), "b9")


def test_a_beat_with_every_shot_locked_cannot_be_regenerated() -> None:
    board = _board()
    for sh in board.beats[1].shots:
        sh.locked = True
    with pytest.raises(DraftError, match="every shot in this beat is locked"):
        regenerate.slots(board, "b2")


def test_new_picks_fill_the_free_slots_around_the_fixed_ones() -> None:
    board = _board()
    sl = regenerate.slots(board, "b1")
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in range(1, 11)}
    out = regenerate.merge(
        board, sl, _answer("seg_000008", "seg_000009", "seg_000002", "seg_000003"), cands
    )
    shots = out.beat("b1")[1].shots
    assert [s.segment_id for s in shots] == [
        "seg_000001",  # locked, slot 0
        "seg_000008",
        "seg_000009",
        "seg_000004",  # locked, slot 3
        "seg_000005",  # absorbed into it, slot 4
        "seg_000002",
        "seg_000003",  # one more than the free slots: appended
    ]
    assert [s.ref for s in shots] == ["b1#0", "b1#6", "b1#7", "b1#3", "b1#4", "b1#8", "b1#9"]
    assert out.beat("b2")[1].shots == board.beat("b2")[1].shots
    assert board.beat("b1")[1].shots[1].segment_id == "seg_000002", "the input is unchanged"


def test_answers_are_checked_against_the_pool_and_the_slots() -> None:
    pool = {"seg_000002", "seg_000003", "seg_000008"}
    assert regenerate.check(_answer("seg_000008", "seg_000002"), "b1", pool, 2) == []
    problems = regenerate.check(_answer("seg_000007"), "b1", pool, 2)
    assert "seg_000007 is not in the pool" in problems
    assert "choose at least 2 shots: one for every free slot" in problems
    assert "seg_000002 is chosen twice" in regenerate.check(
        _answer("seg_000002", "seg_000002"), "b1", pool, 1
    )
    assert "beat_id must be b1" in regenerate.check(_answer("seg_000002", beat="b2"), "b1", pool, 1)


def _cand(ref: str) -> Candidate:
    n = int(ref[4:])
    return Candidate(
        segment_id=n,
        asset_id=n,
        shot_id=n,
        tb="1/1000",
        rate="30/1",
        start=0,
        end=4000,
        usable_start=0,
        usable_end=4000,
        has_speech=False,
        status="USE",
        user_use=False,
        capture=None,
        day=1,
        quality=0.5,
        group_id=None,
        shake_percentile=None,
    )


def test_a_pool_too_small_for_the_slots_is_refused_before_any_ai_call() -> None:
    sl = regenerate.slots(_board(), "b1")  # needs 2 picks before the last locked shot
    assert regenerate.pool_problem([], sl, "Arrival").startswith("no clips left")
    assert "1 clips left for 2 free slots" in regenerate.pool_problem(["seg_000008"], sl, "Arrival")
    assert regenerate.pool_problem(["seg_000008", "seg_000009"], sl, "Arrival") is None


def test_new_refs_never_reuse_one_the_edit_had() -> None:
    board = _board()
    sl = regenerate.slots(board, "b1")
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in range(1, 11)}
    out = regenerate.merge(board, sl, _answer("seg_000008", "seg_000009"), cands, {"b1#12"})
    assert [
        s.ref for s in out.beat("b1")[1].shots if s.segment_id in ("seg_000008", "seg_000009")
    ] == [
        "b1#13",
        "b1#14",
    ]
