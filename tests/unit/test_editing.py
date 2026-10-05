"""Editing units (M0 step 10): request, retrieval cap, solver, refiner, critic, validation."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.ai.prompts.planner.schema_v1 import Output as PlanOut
from mosaic.ai.prompts.selector.schema_v1 import Output as SelectOut
from mosaic.core.time import Rounding
from mosaic.editing import critic, refiner, solver
from mosaic.editing.generate import check_plan, check_selection
from mosaic.editing.request import (
    EditRequest,
    dominant_rate,
    pace_frames,
    parse_fps,
    target_frames,
)
from mosaic.editing.retrieval import Candidate, cap_by_day, parse_ref, seg_ref

RATE = "30000/1001"
TB = "1/90000"
SEC = 90000  # ticks per second at 1/90000


def cand(
    sid: int,
    *,
    asset: int = 1,
    shot: int | None = None,
    start_s: float = 0,
    length_s: float = 10,
    speech: bool = False,
    day: int = 1,
    group: int | None = None,
    user_use: bool = False,
    score_hint: str = "medium",
    src_rate: str | None = "30",
) -> Candidate:
    a = int(start_s * SEC)
    b = a + int(length_s * SEC)
    return Candidate(
        segment_id=sid,
        asset_id=asset,
        shot_id=shot if shot is not None else sid,
        tb=TB,
        rate=src_rate,
        start=a,
        end=b,
        usable_start=a,
        usable_end=b,
        has_speech=speech,
        status="USE",
        user_use=user_use,
        capture=None,
        day=day,
        quality=0.0,
        group_id=group,
        shake_percentile=0.4,
        obs={"interest": score_hint, "composition": "good"},
    )


def shot(
    c: Candidate, beat: str = "b1", order: int = 0, priority: int = 3, **kw: Any
) -> solver.Shot:
    return solver.Shot(
        cand=c,
        beat_id=beat,
        beat_index=int(beat[1:]) - 1,
        order=order,
        role=kw.get("role", "b_roll"),
        priority=priority,
        length=kw.get("length", "medium"),
        audio_intent=kw.get("audio", "natural_sound"),
        reason="r",
        locked=kw.get("locked", False),
    )


# ------------------------------------------------------------------- request


def test_request_and_rates() -> None:
    assert parse_fps("29.97") == "30000/1001"
    assert parse_fps("25") == "25/1"
    with pytest.raises(ValueError, match=r"positive|unsupported"):
        parse_fps("0")
    with pytest.raises(ValueError, match="unsupported"):
        parse_fps("500")
    with pytest.raises(ValueError, match="unknown story"):
        EditRequest(duration_s=60, story="nope")
    assert EditRequest(duration_s=60, fps="59.94").fps == "60000/1001"
    assert target_frames(180, RATE) == 5395  # 180 s × 29.97
    p = pace_frames("balanced", RATE)
    assert (p.min, p.preferred, p.max) == (45, 105, 240)
    # By duration: 100 s of 30000/1001 beats 40 s of 60; 120 fps never sets the timeline.
    assets = [("30000/1001", 100 * SEC, TB), ("60", 40 * SEC, TB), ("120", 900 * SEC, TB)]
    assert dominant_rate(assets) == "30000/1001"
    assert dominant_rate([]) == "30000/1001"


def test_refs() -> None:
    assert seg_ref(451) == "seg_000451"
    assert parse_ref("seg_000451") == 451
    assert parse_ref("evt_1") is None


def test_cap_by_day_keeps_every_day_and_user_picks() -> None:
    cands = [cand(i, day=1) for i in range(1, 91)] + [cand(i, day=2) for i in range(91, 101)]
    cands.append(cand(500, day=1, user_use=True, score_hint="low"))
    kept = cap_by_day(cands, 30)
    assert len(kept) <= 30
    assert any(c.segment_id == 500 for c in kept)
    assert sum(1 for c in kept if c.day == 2) >= 3


# -------------------------------------------------------------------- solver


def test_fit_drops_by_priority_and_lands_on_target() -> None:
    pace = pace_frames("balanced", RATE)
    shots = [shot(cand(i), order=i, priority=5 - (i % 5)) for i in range(12)]
    target = target_frames(30, RATE)
    f = solver.fit(shots, {"b1": 100}, target, target // 20, pace, RATE)
    assert f.total == target
    assert not f.underfilled
    assert f.dropped
    assert min(s.priority for s in f.dropped) <= min(s.priority for s in f.shots)
    assert all(pace.min <= s.frames <= pace.max for s in f.shots)


def test_fit_reports_underfill_and_keeps_locked() -> None:
    pace = pace_frames("balanced", RATE)
    shots = [shot(cand(1, length_s=3)), shot(cand(2, length_s=3), order=1, locked=True)]
    f = solver.fit(shots, {"b1": 100}, target_frames(60, RATE), 90, pace, RATE)
    assert f.underfilled
    assert "not enough usable footage" in " ".join(f.notes)
    # A shot shorter than the minimum is dropped, unless locked.
    tiny = [shot(cand(1, length_s=1)), shot(cand(2, length_s=1), order=1, locked=True)]
    f = solver.fit(tiny, {"b1": 100}, 300, 15, pace, RATE)
    assert [s.cand.segment_id for s in f.shots] == [2]


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(2, 30),
            st.integers(1, 5),
            st.sampled_from(["short", "medium", "long", "hold"]),
        ),
        min_size=1,
        max_size=25,
    ),
    st.integers(10, 120),
)
def test_fit_properties(specs: list[tuple[int, int, str]], seconds: int) -> None:
    pace = pace_frames("balanced", RATE)
    shots = [
        shot(cand(i, length_s=L), beat=f"b{1 + i % 3}", order=i, priority=p, length=ln)
        for i, (L, p, ln) in enumerate(specs)
    ]
    target = target_frames(seconds, RATE)
    tol = target // 20
    f = solver.fit(shots, {"b1": 40, "b2": 30, "b3": 30}, target, tol, pace, RATE)
    assert f.total == sum(s.frames for s in f.shots)
    for s in f.shots:
        assert s.frames <= solver.available_frames(s.cand, RATE)
        assert s.lo <= s.frames <= s.hi
    if not f.underfilled:
        assert abs(f.total - target) <= tol
    # Every beat that had shots keeps at least one.
    assert {s.beat_id for s in shots} == {s.beat_id for s in f.shots}


def test_order_by_chronology() -> None:
    a = shot(cand(1, start_s=50), beat="b1", order=0)
    b = shot(cand(2, start_s=10), beat="b1", order=1)
    c = shot(cand(3, start_s=0), beat="b2", order=0)
    assert [s.cand.segment_id for s in solver.order_shots([a, b, c], "story")] == [1, 2, 3]
    assert [s.cand.segment_id for s in solver.order_shots([a, b, c], "mostly")] == [2, 1, 3]
    assert [s.cand.segment_id for s in solver.order_shots([a, b, c], "strict")] == [3, 2, 1]


# ------------------------------------------------------------------- refiner


def _t(x: float) -> int:
    return int(x * SEC)


def _ctx(
    words: Sequence[tuple[float, float]] = (), sentences: Sequence[tuple[float, float]] = ()
) -> refiner.ClipContext:
    return refiner.ClipContext(
        words=[(_t(a), _t(b)) for a, b in words], sentences=[(_t(a), _t(b)) for a, b in sentences]
    )


def test_refine_never_cuts_inside_a_word() -> None:
    pace = pace_frames("balanced", RATE)
    words = [(i * 0.5 + 0.05, i * 0.5 + 0.45) for i in range(40)]  # speech for 20 s
    c = cand(1, length_s=20, speech=True)
    s = shot(c, audio="natural_sound")
    s.lo, s.hi = solver.bounds(s, pace, RATE)
    s.frames = 100
    cut = refiner.refine(s, _ctx(words), pace, RATE)
    m = refiner.margin_ticks(Fraction(1, 90000))
    for t in (cut.src_in, cut.src_out):
        assert refiner.word_at(t, cut.ctx.words, m) is None
    assert c.usable_start <= cut.src_in < cut.src_out <= c.usable_end
    # Whole timeline frames; the in point is on the source frame grid (30 fps = 3000 ticks).
    assert cut.src_in % 3000 == 0
    assert cut.src_out - cut.src_in == refiner.ticks_for_frames(
        cut.frames, RATE, Fraction(1, 90000), Rounding.CEIL
    )


def test_dialogue_ends_on_a_sentence() -> None:
    pace = pace_frames("balanced", RATE)
    sentences = [(0.5, 4.0), (4.3, 9.0), (9.4, 15.0)]
    # words lie inside their sentences, as in real transcripts
    words = [
        (x, x + 0.25)
        for a, b in sentences
        for x in [a + 0.3 * i for i in range(int((b - a) / 0.3))]
        if x + 0.25 <= b
    ]
    c = cand(1, length_s=16, speech=True)
    s = shot(c, audio="dialogue")
    s.lo, s.hi = solver.bounds(s, pace, RATE)
    s.frames = 180  # 6 s: would end inside sentence 2
    cut = refiner.refine(s, _ctx(words, sentences), pace, RATE)
    ends = [int(e * SEC) for _, e in sentences]
    tb = Fraction(1, 90000)
    m = refiner.margin_ticks(tb)
    assert not any(
        refiner.inside(cut.src_out, (int(a * SEC), int(b * SEC)), m) for a, b in sentences
    )
    assert min(abs(cut.src_out - e) for e in ends) < 3 * 3003  # within a frame or so of an end
    assert cut.src_in == int(0.5 * SEC) // 3000 * 3000 or cut.src_in >= int(0.5 * SEC) - 3000


def _cut(c: Candidate, a_s: float, b_s: float, **kw: Any) -> refiner.Cut:
    s = shot(c, **kw)
    s.hi = 240
    a, b = int(a_s * SEC), int(b_s * SEC)
    return refiner.Cut(
        s,
        a,
        b,
        refiner.frames_for_ticks(b - a, RATE, Fraction(1, 90000), Rounding.FLOOR),
        refiner.ClipContext(),
        [s.selection_ref],
    )


def test_jump_cuts_merge_swap_or_drop() -> None:
    pace = pace_frames("balanced", RATE)
    # Same take, in order, 1 s apart: merged into one continuous shot.
    take = cand(1, length_s=30, shot=7)
    take2 = cand(2, length_s=30, shot=7)
    cuts = [_cut(take, 0, 3), _cut(take2, 4, 7)]
    out, notes = refiner.fix_jump_cuts(cuts, RATE, pace)
    assert len(out) == 1
    assert "merged" in notes[0]
    assert out[0].src_in == 0
    assert 7 * SEC - 3003 < out[0].src_out <= 7 * SEC  # frame-aligned end of the second take
    # Different shots of one recording: a cut from another asset is moved between them.
    x, y, z = cand(3, shot=1), cand(4, shot=2, start_s=10), cand(5, asset=2)
    out, notes = refiner.fix_jump_cuts([_cut(x, 0, 3), _cut(y, 4, 7), _cut(z, 0, 3)], RATE, pace)
    assert [c.shot.cand.asset_id for c in out] == [1, 2, 1]
    # Nothing to swap with: the lower-priority one goes.
    p, q = cand(6, shot=1), cand(7, shot=2, start_s=10)
    out, _ = refiner.fix_jump_cuts(
        [_cut(p, 0, 3, priority=5), _cut(q, 4, 7, priority=2)], RATE, pace
    )
    assert [c.shot.cand.segment_id for c in out] == [6]
    assert not refiner.is_jump(_cut(p, 0, 3), _cut(cand(8, asset=2), 0, 3))


def test_backfill_and_land_on_target() -> None:
    pace = pace_frames("balanced", RATE)
    cuts = [_cut(cand(1, asset=1), 0, 3), _cut(cand(2, asset=2), 0, 3)]
    spare = shot(cand(3, asset=3), order=1, priority=2)
    out, notes = refiner.backfill(cuts, [(spare, refiner.ClipContext())], 400, 20, pace, RATE)
    assert len(out) == 3
    assert notes
    left = refiner.land_on_target(out, 400, RATE, pace)
    assert left == 0
    assert sum(c.frames for c in out) == 400
    evts = refiner.events(out, RATE)
    assert evts[0]["timeline_in"] == {"frames": 0, "rate": RATE}
    assert evts[-1]["timeline_out"]["frames"] == 400
    for a, b in itertools.pairwise(evts):
        assert a["timeline_out"] == b["timeline_in"]
    assert all(isinstance(e["source_in"]["ticks"], int) for e in evts)


# -------------------------------------------------------------------- critic


def test_critic_counts_blocking_problems() -> None:
    tb = Fraction(1, 90000)
    c1 = _cut(cand(1, asset=1, group=9), 0, 3, audio="dialogue")
    c1.ctx = refiner.ClipContext(
        words=[(int(2.9 * SEC), int(3.4 * SEC))], sentences=[(0, int(5 * SEC))]
    )
    c2 = _cut(cand(2, asset=1, start_s=3.5, group=9), 3.5, 6)
    metrics, findings = critic.evaluate([c1, c2], 300, 15, RATE, {2}, {1, 2}, ["b1", "b2"])
    assert metrics["mid_word_cuts"] == 1
    assert metrics["dialogue_truncations"] == 1
    assert metrics["adjacent_jump_cuts"] == 1
    assert metrics["reject_used"] == 1
    assert metrics["same_group_within_5"] == 1
    assert not metrics["duration_ok"]
    assert not metrics["blocking_ok"]
    assert {f.code for f in findings} >= {
        "mid_word",
        "dialogue_truncation",
        "jump_cut",
        "reject_used",
        "duration",
        "beat_coverage",
    }
    assert refiner.margin_ticks(tb) == 1800


# ----------------------------------------------------------------- validation


def test_plan_and_selection_checks() -> None:
    refs = {"seg_000001", "seg_000002", "seg_000003"}
    plan = PlanOut.model_validate(
        {
            "title": "Trip",
            "beats": [
                {
                    "beat_id": "b1",
                    "title": "Start",
                    "intent": "Open",
                    "share_percent": 60,
                    "candidates": ["seg_000001", "seg_000009"],
                },
                {
                    "beat_id": "b1",
                    "title": "End",
                    "intent": "Close",
                    "share_percent": 20,
                    "candidates": ["seg_000002"],
                },
            ],
        }
    )
    errors = "\n".join(check_plan(plan, refs))
    for text in ("unique", "adds up to 80", "seg_000009"):
        assert text in errors
    good = PlanOut.model_validate(
        {
            "title": "Trip",
            "beats": [
                {
                    "beat_id": "b1",
                    "title": "Start",
                    "intent": "Open",
                    "share_percent": 50,
                    "candidates": ["seg_000001"],
                },
                {
                    "beat_id": "b2",
                    "title": "End",
                    "intent": "Close",
                    "share_percent": 50,
                    "candidates": ["seg_000002"],
                },
            ],
        }
    )
    assert check_plan(good, refs) == []
    sel = {
        "segment_id": "seg_000001",
        "role": "opener",
        "priority": 5,
        "length": "long",
        "audio_intent": "natural_sound",
        "reason": "Opens.",
        "alternatives": [{"segment_id": "seg_000008", "why_not": "worse"}],
    }
    answer = SelectOut.model_validate({"beats": [{"beat_id": "b1", "selections": [sel, sel]}]})
    errors = "\n".join(check_selection(answer, good, refs))
    for text in ("b1, b2", "more than once", "seg_000008"):
        assert text in errors
    with pytest.raises(ValueError, match="timeline_in"):
        SelectOut.model_validate(
            {"beats": [{"beat_id": "b1", "selections": [sel | {"timeline_in": 3}]}]}
        )


def test_merge_of_adjacent_segments_keeps_the_second_segment() -> None:
    """Real segments of one take sit end to end: the merged cut must reach into the second."""
    pace = pace_frames("balanced", RATE)
    first = cand(1, shot=7, start_s=0, length_s=5)
    second = cand(2, shot=7, start_s=5, length_s=5)
    cuts = [_cut(first, 2, 5), _cut(second, 5.5, 8)]
    out, notes = refiner.fix_jump_cuts(cuts, RATE, pace)
    assert len(out) == 1
    assert "merged" in notes[0]
    assert [m.cand.segment_id for m in out[0].merged_shots] == [2]
    evt = refiner.events(out, RATE)[0]
    assert evt["origin"]["merged_segments"] == ["seg_000002"]
    assert out[0].src_out > second.usable_start
    assert out[0].src_out <= second.usable_end
    assert out[0].ub == second.usable_end


@settings(max_examples=150, deadline=None)
@given(
    st.integers(0, 600),  # usable start, tenths of a second
    st.integers(8, 300),  # usable length, tenths
    st.integers(1, 400),  # requested frames
    st.lists(st.tuples(st.integers(0, 900), st.integers(2, 8)), max_size=20),  # words
    st.sampled_from(["30", "30000/1001", "25", None]),
    st.booleans(),
)
def test_refine_properties(
    start: int,
    length: int,
    frames: int,
    words: list[tuple[int, int]],
    src_rate: str | None,
    dialogue: bool,
) -> None:
    pace = pace_frames("balanced", RATE)
    c = cand(1, start_s=start / 10, length_s=length / 10, speech=dialogue, src_rate=src_rate)
    s = shot(c, audio="dialogue" if dialogue else "natural_sound")
    s.lo, s.hi = solver.bounds(s, pace, RATE)
    s.frames = max(1, min(frames, s.hi or 1))
    spans = sorted(
        {(c.usable_start + w * 9000, c.usable_start + w * 9000 + d * 9000) for w, d in words}
    )
    cut = refiner.refine(s, refiner.ClipContext(words=spans), pace, RATE)
    tb = Fraction(1, 90000)
    assert c.usable_start <= cut.src_in < cut.src_out <= c.usable_end
    assert cut.frames >= 1
    assert cut.src_out - cut.src_in == refiner.ticks_for_frames(cut.frames, RATE, tb, Rounding.CEIL)
    m = refiner.margin_ticks(tb)
    # A one-frame cut has no shorter fallback; word safety is guaranteed from two frames.
    if cut.frames > 1:
        assert refiner.word_at(cut.src_out, spans, m) is None


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(1, 3), st.integers(0, 50), st.integers(1, 5)), min_size=1, max_size=12
    )
)
def test_jump_fixing_and_landing_properties(spec: list[tuple[int, int, int]]) -> None:
    pace = pace_frames("balanced", RATE)
    cuts = []
    for i, (asset, at, prio) in enumerate(spec):
        if asset == 3:
            # Takes of asset 3 are one shot cut into end-to-end 10 s segments: merges happen.
            start = (at // 10) * 10
            c = cand(100 + i, asset=3, shot=3000, start_s=start, length_s=10)
            cuts.append(_cut(c, start + 1, start + 4, priority=prio, order=i))
            continue
        c = cand(100 + i, asset=asset, shot=1000 + i, start_s=at, length_s=10)
        cuts.append(_cut(c, at + 1, at + 4, priority=prio, order=i))
    out, _ = refiner.fix_jump_cuts(cuts, RATE, pace)
    assert out
    assert not any(refiner.is_jump(a, b) for a, b in itertools.pairwise(out))
    target = sum(c.frames for c in out) + 30
    before = abs(target - sum(c.frames for c in out))
    left = refiner.land_on_target(out, target, RATE, pace)
    assert abs(left) <= before
    assert left == target - sum(c.frames for c in out)
    assert not any(refiner.is_jump(a, b) for a, b in itertools.pairwise(out))
    for c in out:
        assert c.ua <= c.src_in < c.src_out <= c.ub
