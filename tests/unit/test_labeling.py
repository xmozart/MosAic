""" "Help me label" (S24; M4 acceptance 7; ADR 0085): questions from what analysis knows,
answers stored only as trip-context records and person links - never face or biometric
data."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.library import labeling
from mosaic.library.context import Day, Person, TripContext
from mosaic.library.context import load as load_context
from mosaic.library.context import save as save_context
from mosaic.storage import provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import (
    Asset,
    Mosaic,
    PersonLink,
    SampleFrame,
    Segment,
    Shot,
    VisualObservation,
)
from mosaic.storage.projects import Project, init_project

# Day 1 (12 June): three people-clips 10 min apart, two highlights; day 2: three highlights.
CLIPS = [
    ("2026-06-12T09:00:00+00:00", "one", "high"),
    ("2026-06-12T09:10:00+00:00", "few", "medium"),
    ("2026-06-12T09:20:00+00:00", "one", "low"),
    ("2026-06-12T15:00:00+00:00", "none", "high"),
    ("2026-06-13T10:00:00+00:00", "none", "high"),
    ("2026-06-13T11:00:00+00:00", "crowd", "high"),
    ("2026-06-13T12:00:00+00:00", "none", "high"),
]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with p.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="t"))
        save_context(
            s,
            TripContext(
                trip_name="Iceland",
                days=[Day(date="2026-06-13", place="Reykjavík")],
                people=[Person(label="Maya")],
            ),
            "user",
        )
        for i, (when, people, interest) in enumerate(CLIPS):
            a = Asset(kind="video", status="ok", profile="generic", group_key=f"g{i}",
                      created_at="x", provenance_id=prov, capture_time=when)  # fmt: skip
            s.add(a)
            s.flush()
            shot = Shot(asset_id=a.id, index=0, start_ticks=0, end_ticks=90000,
                        method="adaptive", provenance_id=prov)  # fmt: skip
            m = Mosaic(asset_id=a.id, index=0, image_key=f"m{i}", cols=1, rows=1,
                       tile_width=1, tile_height=1, provenance_id=prov)  # fmt: skip
            s.add_all([shot, m])
            s.flush()
            seg = Segment(asset_id=a.id, shot_id=shot.id, index=0, start_ticks=0,
                          end_ticks=90000, usable_start_ticks=0, usable_end_ticks=90000,
                          provenance_id=prov)  # fmt: skip
            s.add(seg)
            s.flush()
            s.add(VisualObservation(segment_id=seg.id, mosaic_id=m.id, provenance_id=prov,
                                    data={"people": people, "interest": interest}))  # fmt: skip
            s.add(SampleFrame(asset_id=a.id, shot_id=shot.id, ticks=0, reason="scene",
                              phash="0" * 16, kept=True, image_key=f"f{i}",
                              provenance_id=prov))  # fmt: skip
    yield p
    p.close()


def _by_kind(items: list[Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for q in items:
        out.setdefault(q.kind, []).append(q)
    return out


def test_questions_come_from_what_the_library_knows(project: Project) -> None:
    qs = _by_kind(labeling.questions(project))
    assert [q.text for q in qs["place"]] == ["Where were you on Day 1 (Friday 12 June)?"]
    same = qs["same_person"][0]
    assert len(same.asset_ids) == 3, "three people-clips within half an hour"
    assert len(same.sample_ids) == 3
    assert qs["event"][0].day == 2, "the day with the most high-interest moments"
    assert len(labeling.questions(project)) == 3, "asked once: the same open questions"


def test_answers_become_context_and_person_links_only(project: Project) -> None:
    qs = _by_kind(labeling.questions(project))
    labeling.answer(project, qs["place"][0].uid, text="  Seljalandsfoss  ")
    labeling.answer(project, qs["event"][0].uid, text="Whale watching from Húsavík")
    same = qs["same_person"][0]
    out = labeling.answer(project, same.uid, choice="yes", name="maya")
    assert out["linked"] == same.asset_ids
    with project.db.session() as s:
        trip = load_context(s)
        assert {d.date: (d.place, d.notes) for d in trip.days} == {
            "2026-06-12": ("Seljalandsfoss", ""),
            "2026-06-13": ("Reykjavík", "Whale watching from Húsavík"),
        }
        assert [p.label for p in trip.people] == ["Maya"], "matched to the context's person"
        links = list(s.execute(select(PersonLink.label, PersonLink.asset_id)))
        assert sorted(links) == [("Maya", a) for a in sorted(same.asset_ids)]
        assert labeling.links(s, same.asset_ids[0]) == ["Maya"]
    with pytest.raises(labeling.AnswerError):
        labeling.answer(project, same.uid, choice="yes", name="Maya")
    answered = {q.subject for kind in qs.values() for q in kind}
    again = labeling.questions(project)
    assert not {q.subject for q in again} & answered, "answered questions are not asked again"
    assert [q.subject for q in again] == ["event:2026-06-12"], "day 1's highlights, now"


def test_a_new_name_joins_the_trip_context_and_skips_record_nothing(project: Project) -> None:
    same = _by_kind(labeling.questions(project))["same_person"][0]
    labeling.answer(project, same.uid, choice="yes", name="Leo")
    with project.db.session() as s:
        assert [p.label for p in load_context(s).people] == ["Maya", "Leo"]
    place = _by_kind(labeling.questions(project))["place"][0]
    with pytest.raises(labeling.AnswerError, match="Type an answer"):
        labeling.answer(project, place.uid, text="   ")
    before = labeling.answer(project, place.uid, skip=True)
    assert before["status"] == "skipped"
    with project.db.session() as s:
        assert "2026-06-12" not in {d.date for d in load_context(s).days}
    with pytest.raises(LookupError):
        labeling.answer(project, "nope", skip=True)


def test_no_face_or_biometric_data_is_stored(project: Project) -> None:
    """M4 acceptance 7: answering every question writes person links and trip-context
    records only, and nothing in the project's schema holds face or biometric data."""
    for q in labeling.questions(project):
        if q.kind == "same_person":
            labeling.answer(project, q.uid, choice="yes", name="Maya")
        else:
            labeling.answer(project, q.uid, text="Somewhere")
    con = sqlite3.connect(project.db.path)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    words = ("face", "biometric", "landmark", "facial", "identity")
    for t in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info('{t}')")]
        assert not any(w in t.lower() for w in words), t
        assert not any(w in c.lower() for c in cols for w in words), (t, cols)
    cols = [r[1] for r in con.execute("PRAGMA table_info('person_link')")]
    assert cols == ["id", "label", "asset_id", "question_id", "created_at"]
    answers = [r[0] for r in con.execute("SELECT answer FROM labeling_question")]
    con.close()
    assert all("embedding" not in (a or "") for a in answers)


def test_the_api_asks_and_records_answers(project: Project) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(ControlDB()))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    items = client.get(f"/api/projects/{project.id}/labeling-questions").json()["items"]
    assert [q["kind"] for q in items] == ["place", "same_person", "event"]
    same = items[1]
    assert same["people"] == ["Maya"], "the name field's suggestions"
    url = f"/api/projects/{project.id}/labeling-questions/{same['question_id']}/answer"
    assert client.post(url, json={"choice": "maybe"}).status_code == 422
    ok = client.post(url, json={"choice": "yes", "name": "Maya"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["linked"] == same["asset_ids"]
    assert client.post(url, json={"choice": "no"}).status_code == 422, "answered already"
    bad = f"/api/projects/{project.id}/labeling-questions/nope/answer"
    assert client.post(bad, json={"skip": True}).status_code == 404


def _add_clip(project: Project, when: str | None) -> None:
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="t"))
        s.add(Asset(kind="video", status="ok", profile="generic", group_key=f"x{when}",
                    created_at="x", provenance_id=prov, capture_time=when))  # fmt: skip


def test_camera_local_and_unknown_times_mix_with_phone_times(project: Project) -> None:
    """Invariant 14: a camera's local time (no zone) and a clip with none at all, among
    phone clips with offsets, never break the questions."""
    _add_clip(project, "2026-06-12T09:05:00")  # camera-local, naive
    _add_clip(project, None)
    kinds = {q.kind for q in labeling.questions(project)}
    assert {"place", "same_person", "event"} <= kinds


def test_an_answer_never_saves_a_context_that_would_not_load(project: Project) -> None:
    with project.write() as s:
        full = TripContext(people=[Person(label=f"P{i}") for i in range(50)])
        save_context(s, full, "user")
    same = _by_kind(labeling.questions(project))["same_person"][0]
    with pytest.raises(labeling.AnswerError, match="as many people"):
        labeling.answer(project, same.uid, choice="yes", name="One more")
    with pytest.raises(labeling.AnswerError, match="Type a name"):
        labeling.answer(project, same.uid, choice="yes", name="  ")
    with project.db.session() as s:
        assert len(load_context(s).people) == 50, "still loads, unchanged"
    with project.db.session() as s:
        assert not list(s.scalars(select(PersonLink)))


def test_a_question_the_trip_context_answers_is_closed(project: Project) -> None:
    place = _by_kind(labeling.questions(project))["place"][0]
    with project.write() as s:
        trip = load_context(s)
        days = [*trip.days, Day(date="2026-06-12", place="Vík")]
        save_context(s, trip.model_copy(update={"days": days}), "user")
    assert place.uid not in {q.uid for q in labeling.questions(project)}
