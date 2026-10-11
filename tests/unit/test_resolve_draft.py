"""``resolve`` for a storyboard the owner shaped (ADR 0067), on hand-built candidates so
the solver must backfill: what the owner took out never returns as a spare, and a spare
lands at its place in the owner's order, not at its place in time."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
from mosaic.editing import solver
from mosaic.editing.request import EditRequest, pace_frames
from mosaic.editing.resolve import EditInputs, resolve
from mosaic.editing.retrieval import Candidate
from mosaic.library.context import TripContext
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import Project, init_project

RATE = "30/1"


def _cand(n: int, seconds: int, minute: int) -> Candidate:
    return Candidate(
        segment_id=n,
        asset_id=n,  # one clip each: no jump cuts
        shot_id=n,
        tb="1/1000",
        rate=RATE,
        start=0,
        end=seconds * 1000,
        usable_start=0,
        usable_end=seconds * 1000,
        has_speech=False,
        status="USE",
        user_use=False,
        capture=datetime(2026, 7, 15, 9, minute, tzinfo=UTC),
        day=1,
        quality=0.5,
        group_id=None,
        shake_percentile=None,
    )


def _shot(c: Candidate, order: int, alts: tuple[Candidate, ...] = (), beat: int = 1) -> solver.Shot:
    return solver.Shot(
        cand=c,
        beat_id=f"b{beat}",
        beat_index=beat - 1,
        order=order,
        role="b_roll",
        priority=3,
        length="medium",
        audio_intent="natural_sound",
        reason="Picked",
        alternatives=[{"segment_id": a.ref, "why_not": "Softer"} for a in alts],
        ref=f"b{beat}#{order}",
    )


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    yield p
    p.close()


def _run(project: Project, *, user_order: bool, excluded: set[str]) -> list[str]:
    # B, D, A in the owner's order, though A was filmed first; X (D's alternative) was
    # filmed before all of them. 9 s of material for a 30 s edit: the solver backfills X.
    a, b, d, x = _cand(1, 3, 1), _cand(2, 3, 2), _cand(3, 3, 3), _cand(4, 3, 0)
    e = _cand(5, 3, 30)  # the closing beat's one shot
    cands = [a, b, d, x, e]
    req = EditRequest(duration_s=30, chronology="strict")
    inp = EditInputs(RATE, pace_frames("balanced", RATE), cands, {}, "digest", TripContext())
    plan = PlanOut(
        title="Trip",
        beats=[
            {
                "beat_id": "b1",
                "title": "Arrival",
                "intent": "Arrive",
                "share_percent": 80,
                "candidates": [c.ref for c in cands[:4]],
            },
            {
                "beat_id": "b2",
                "title": "Home",
                "intent": "Leave",
                "share_percent": 20,
                "candidates": [e.ref],
            },
        ],
    )
    shots = [_shot(b, 0), _shot(d, 1, (x,)), _shot(a, 2), _shot(e, 0, beat=2)]
    with project.db.session() as s:
        done = resolve(s, req, inp, plan, shots, set(), user_order=user_order, excluded=excluded)
    return [e["segment_id"] for e in done.timeline["tracks"][0]["events"]]


def test_a_spare_lands_in_the_owners_order(project: Project) -> None:
    b, d, a, x = "seg_000002", "seg_000003", "seg_000001", "seg_000004"
    assert _run(project, user_order=True, excluded=set()) == [b, d, x, a, "seg_000005"]
    # Without the owner's order the chronology rules: X, filmed first, opens the edit.
    assert _run(project, user_order=False, excluded=set())[0] == x


def test_what_the_owner_took_out_is_never_a_spare(project: Project) -> None:
    assert "seg_000004" in _run(project, user_order=True, excluded=set())
    assert "seg_000004" not in _run(project, user_order=True, excluded={"seg_000004"})


def _timed(project: Project, shots: list[solver.Shot], seconds: int) -> Any:
    cands = [sh.cand for sh in shots] + [x.cand for sh in shots for x in sh.absorbed]
    req = EditRequest(duration_s=seconds, chronology="story")
    inp = EditInputs(RATE, pace_frames("balanced", RATE), cands, {}, "digest", TripContext())
    plan = PlanOut(
        title="Trip",
        beats=[
            {
                "beat_id": "b1",
                "title": "Arrival",
                "intent": "Arrive",
                "share_percent": 80,
                "candidates": [c.ref for c in cands],
            },
            {
                "beat_id": "b2",
                "title": "Home",
                "intent": "Leave",
                "share_percent": 20,
                "candidates": [cands[0].ref],
            },
        ],
    )
    with project.db.session() as s:
        return resolve(s, req, inp, plan, shots, set())


def test_a_pinned_shot_keeps_its_exact_cut_while_the_rest_is_trimmed(project: Project) -> None:
    """A lock keeps the shot's source range and frames (ADR 0068): the solver fits the
    edit around it, trimming only the others."""
    long = [_cand(n, 8, n) for n in range(1, 6)]  # 40 s of material for a 12 s edit
    shots = [_shot(c, i) for i, c in enumerate(long)]
    shots[2].locked = True
    shots[2].pin = (1234, 1234 + 5000, 150)  # 5 s from 1.234 s, at 30 fps
    done = _timed(project, shots, 12)
    events = done.timeline["tracks"][0]["events"]
    pinned = next(e for e in events if e["origin"]["selection_ref"] == "b1#2")
    assert pinned["source_in"]["ticks"] == 1234
    assert pinned["source_out"]["ticks"] == 6234
    assert pinned["timeline_out"]["frames"] - pinned["timeline_in"]["frames"] == 150
    assert pinned["origin"]["locked"]
    assert done.timeline["duration"]["frames"] == 360, "the others absorb the trim"
    assert done.metrics["locks"] == {"shots": 1, "pinned": 1, "frames": 150, "over_frames": 0}
    stored = next(sh for sh in done.beats[0]["shots"] if sh["ref"] == "b1#2")
    assert stored["pin"] == {
        "segment_id": "seg_000003",
        "source_in": {"ticks": 1234, "tb": "1/1000"},
        "source_out": {"ticks": 6234, "tb": "1/1000"},
        "duration": {"frames": 150, "rate": RATE},
    }


def test_locks_longer_than_the_target_are_reported_in_frames(project: Project) -> None:
    long = [_cand(n, 8, n) for n in range(1, 4)]
    shots = [_shot(c, i) for i, c in enumerate(long)]
    for i in (0, 1):
        shots[i].locked = True
        shots[i].pin = (0, 7000, 210)  # 7 s each: 14 s of locks for a 10 s edit
    done = _timed(project, shots, 10)
    locks = done.metrics["locks"]
    assert locks["frames"] == 420
    assert locks["over_frames"] == 420 - (300 + 300 * 5 // 100)
    assert done.metrics["solver"]["notes"][0].startswith("locked shots exceed the target")
    kept = [e["origin"]["selection_ref"] for e in done.timeline["tracks"][0]["events"]]
    assert {"b1#0", "b1#1"} <= set(kept), "locks are never dropped to fit"


def test_the_solver_budgets_a_pinned_shot_at_its_own_length() -> None:
    shots = [_shot(_cand(n, 8, n), n - 1) for n in range(1, 5)]
    shots[1].locked = True
    shots[1].pin = (0, 2000, 60)  # 2 s: shorter than its length would make it
    fit = solver.fit(shots, {"b1": 100}, 300, 15, pace_frames("balanced", RATE), RATE)
    pinned = next(s for s in fit.shots if s.selection_ref == "b1#1")
    assert (pinned.lo, pinned.frames, pinned.hi) == (60, 60, 60)
    assert fit.total == sum(s.frames for s in fit.shots)


def test_pinning_the_second_pick_of_a_merged_cut() -> None:
    from mosaic.editing.draft import Board, LockShot, pinned
    from mosaic.editing.resolve import Resolved

    def pick(ref: str, seg: str) -> dict[str, Any]:
        return {
            "ref": ref,
            "segment_id": seg,
            "role": "b_roll",
            "priority": 3,
            "length": "medium",
            "audio_intent": "natural_sound",
            "reason": "r",
        }

    board = Board.model_validate(
        {
            "title": "Trip",
            "beats": [
                {
                    "beat_id": "b1",
                    "title": "Arrival",
                    "intent": "Arrive",
                    "share_percent": 50,
                    "pool": ["seg_000001", "seg_000002"],
                    "shots": [pick("b1#0", "seg_000001"), pick("b1#1", "seg_000002")],
                }
            ],
        }
    )
    event = {
        "segment_id": "seg_000001",
        "source_in": {"ticks": 100, "tb": "1/1000"},
        "source_out": {"ticks": 9100, "tb": "1/1000"},
        "timeline_in": {"frames": 30, "rate": RATE},
        "timeline_out": {"frames": 300, "rate": RATE},
        "origin": {"selection_ref": "b1#0", "merged": ["b1#1"], "locked": False},
    }
    done = Resolved({"rate": RATE, "tracks": [{"kind": "video", "events": [event]}]}, [], {}, [])
    op = pinned(LockShot(ref="b1#1"), done, board)
    assert op.pin is not None
    assert op.pin.segment_id == "seg_000002", "the pin names the locked pick's own segment"
    assert (op.pin.source_in.ticks, op.pin.source_out.ticks, op.pin.duration.frames) == (
        100,
        9100,
        270,
    )
    assert op.absorb == ["b1#0"]
    assert pinned(LockShot(ref="b1#1", locked=False, pin=op.pin), done, board).pin is None


def test_absorbed_footage_stays_in_its_locked_cut_and_is_never_a_spare(project: Project) -> None:
    a, b, x = _cand(1, 8, 1), _cand(2, 3, 2), _cand(3, 3, 3)
    locker = _shot(a, 0)
    locker.locked = True
    locker.pin = (0, 4000, 120)
    inside = _shot(x, 1)  # cut as part of the locked shot
    other = _shot(b, 2, (x,))  # names x as its alternative
    locker.absorbed.append(inside)
    done = _timed(project, [locker, other], 30)  # far too short: the solver backfills
    events = done.timeline["tracks"][0]["events"]
    locked = next(e for e in events if e["origin"]["selection_ref"] == "b1#0")
    assert locked["origin"]["merged"] == ["b1#1"]
    assert locked["origin"]["merged_segments"] == [x.ref]
    assert [e["segment_id"] for e in events].count(x.ref) == 0, "never added again as a spare"
    assert done.timeline["selections"]["b1#1"]["used"]
