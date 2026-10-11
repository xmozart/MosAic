"""``resolve`` for a storyboard the owner shaped (ADR 0067), on hand-built candidates so
the solver must backfill: what the owner took out never returns as a spare, and a spare
lands at its place in the owner's order, not at its place in time."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

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
