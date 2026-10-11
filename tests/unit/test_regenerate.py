"""Regenerating one beat (ADR 0069): the slots, the answer's checks and how new picks
fill the free slots around the locked shots."""

from __future__ import annotations

from typing import Any

import pytest

from mosaic.ai.prompts.reselect.schema_v1 import Output as ReselectOut
from mosaic.editing import regenerate
from mosaic.editing.draft import Board, DraftError, Pin
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


def test_variants_never_collide() -> None:
    seen = {regenerate.pair(a, b) for a in range(60) for b in range(60)}
    assert len(seen) == 3600


def test_the_story_is_made_from_the_edits_own_clips() -> None:
    board = _board()
    cands = [_cand(f"seg_{n:06d}") for n in (1, 2, 7, 8, 99)]
    story = regenerate.scope_candidates("story", board, cands)
    assert [c.ref for c in story] == ["seg_000001", "seg_000002", "seg_000007"]
    everything = regenerate.scope_candidates("all", board, cands)
    assert [c.ref for c in everything] == ["seg_000001", "seg_000002", "seg_000007", "seg_000008"]


def _plan_and_selection(
    picks: dict[str, list[str]], pools: dict[str, list[str]]
) -> tuple[Any, Any]:
    from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
    from mosaic.ai.prompts.selector.schema_v2 import Output as SelectOut

    plan = PlanOut.model_validate(
        {
            "title": "New",
            "beats": [
                {
                    "beat_id": b,
                    "title": f"Beat {b}",
                    "intent": "New intent",
                    "share_percent": 50,
                    "candidates": pools[b],
                }
                for b in picks
            ],
        }
    )
    sel = SelectOut.model_validate(
        {
            "beats": [
                {
                    "beat_id": b,
                    "selections": [
                        {
                            "segment_id": r,
                            "role": "b_roll",
                            "priority": 3,
                            "length": "medium",
                            "audio_intent": "natural_sound",
                            "reason": "New",
                            "alternatives": [],
                        }
                        for r in refs
                    ],
                }
                for b, refs in picks.items()
            ]
        }
    )
    return plan, sel


def test_a_new_story_gets_refs_no_version_used() -> None:
    plan, sel = _plan_and_selection(
        {"b1": ["seg_000002"], "b2": ["seg_000003"]}, {"b1": ["seg_000002"], "b2": ["seg_000003"]}
    )
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in range(1, 11)}
    board = regenerate.board_from_selection(plan, sel, cands, {"b1#0", "b1#4", "b2#0"})
    assert [[s.ref for s in b.shots] for b in board.beats] == [["b1#5"], ["b2#1"]]


def test_locked_shots_are_carried_into_a_new_story() -> None:
    old = _board()  # locked: b1#0 (seg 1), b1#3 (seg 4) with b1#4 (seg 5) absorbed
    pin = {
        "segment_id": "seg_000004",
        "source_in": {"ticks": 0, "tb": "1/1000"},
        "source_out": {"ticks": 3000, "tb": "1/1000"},
        "duration": {"frames": 90, "rate": "30/1"},
    }
    old.beats[0].shots[3].pin = Pin.model_validate(pin)
    # The new selection picks seg 1 in b2, seg 5 (absorbed) on its own, not seg 4 at all.
    plan, sel = _plan_and_selection(
        {"b1": ["seg_000008", "seg_000005"], "b2": ["seg_000009", "seg_000001"]},
        {"b1": ["seg_000008", "seg_000004", "seg_000005"], "b2": ["seg_000009", "seg_000001"]},
    )
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in range(1, 11)}
    new = regenerate.carry_locks(
        regenerate.board_from_selection(plan, sel, cands, {"b1#9"}), old, cands
    )
    b1, b2 = (b.shots for b in new.beats)
    # seg 1 stays where the new selection put it, as the locked shot with its ref.
    assert [s.segment_id for s in b2] == ["seg_000009", "seg_000001"]
    assert b2[1].ref == "b1#0"
    assert b2[1].locked
    # seg 4 goes into b1 (its pool holds it) in time order, with its absorbed pick and
    # its pin; the new selection's own pick of seg 5 is dropped.
    assert [s.segment_id for s in b1] == ["seg_000004", "seg_000005", "seg_000008"]
    assert b1[0].pin is not None
    assert b1[0].pin.duration.frames == 90
    assert b1[1].absorbed_by == "b1#3"
    assert new.excluded == ["seg_000099"]
    assert not new.user_order


def test_a_lock_no_new_pool_holds_goes_to_the_beat_filmed_around_it() -> None:
    from datetime import UTC, datetime

    old = _board()
    plan, sel = _plan_and_selection(
        {"b1": ["seg_000002"], "b2": ["seg_000006"]},
        {"b1": ["seg_000002"], "b2": ["seg_000006"]},
    )
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in range(1, 11)}
    times = {
        "seg_000002": 9,
        "seg_000006": 30,
        "seg_000001": 10,
        "seg_000004": 40,
        "seg_000005": 41,
    }
    for ref, minute in times.items():
        cands[ref].capture = datetime(2026, 7, 15, 9, minute, tzinfo=UTC)
    new = regenerate.carry_locks(
        regenerate.board_from_selection(plan, sel, cands, set()), old, cands
    )
    b1, b2 = new.beats
    # seg 1 (09:10) follows seg 2 (09:09) in b1; seg 4 and its absorbed seg 5 follow seg 6 in b2.
    assert [s.segment_id for s in b1.shots] == ["seg_000002", "seg_000001"]
    assert [s.segment_id for s in b2.shots] == ["seg_000006", "seg_000004", "seg_000005"]
    assert {"seg_000004", "seg_000005"} <= set(b2.pool), "the whole locked cut is in the pool"
    assert "seg_000001" in b1.pool


def test_a_lock_whose_clip_is_gone_is_kept_at_the_end() -> None:
    old = _board()
    plan, sel = _plan_and_selection({"b1": ["seg_000002"]}, {"b1": ["seg_000002"]})
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in (2,)}  # 1, 4 and 5 are gone
    new = regenerate.carry_locks(
        regenerate.board_from_selection(plan, sel, cands, set()), old, cands
    )
    assert [s.segment_id for s in new.beats[0].shots] == [
        "seg_000002",
        "seg_000001",
        "seg_000004",
        "seg_000005",
    ]


def test_a_pin_from_another_frame_rate_is_recut_not_kept() -> None:
    from mosaic.editing.draft import board_shots

    board = _board()
    shot = board.beats[0].shots[3]
    shot.pin = Pin.model_validate(
        {
            "segment_id": "seg_000004",
            "source_in": {"ticks": 0, "tb": "1/1000"},
            "source_out": {"ticks": 3000, "tb": "1/1000"},
            "duration": {"frames": 75, "rate": "25/1"},
        }
    )
    cands = {f"seg_{n:06d}": _cand(f"seg_{n:06d}") for n in range(1, 11)}
    _, shots, notes = board_shots(board, cands, "30/1")
    locked = next(s for s in shots if s.selection_ref == "b1#3")
    assert locked.locked
    assert locked.pin is None, "re-cut at the new rate"
    assert any("no longer applies" in n for n in notes)
    _, shots, _ = board_shots(board, cands, "25/1")
    assert next(s for s in shots if s.selection_ref == "b1#3").pin == (0, 3000, 75)
