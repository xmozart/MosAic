"""Edit generation on the analyzed synthetic corpus with the fake AI (M0 step 10)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.core.timecheck import find_float_times
from mosaic.editing.generate import export_path
from mosaic.editing.request import EditRequest
from mosaic.editing.service import create_edit, get_version, report, report_text, submit_generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Disposition, EditVersion, Segment, Shot
from mosaic.storage.projects import Project
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


def _generate(project: Project, control: ControlDB, request: EditRequest) -> int:
    edit_id = create_edit(project, request, control, control.local_principal)
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    return edit_id


@pytest.fixture(scope="module")
def edited(analyzed_session: Any) -> tuple[Project, ControlDB, int]:
    project, control = analyzed_session
    return project, control, _generate(project, control, EditRequest(duration_s=30))


def test_edit_meets_every_blocking_metric(edited: tuple[Project, ControlDB, int]) -> None:
    project, _, edit_id = edited
    v = get_version(project, edit_id)
    m = v.metrics
    assert m["blocking_ok"], (m, v.findings)
    assert m["total_frames"] == m["target_frames"]
    assert v.rate == "30000/1001"  # the dominant source rate of the corpus
    events = v.timeline["tracks"][0]["events"]
    assert events
    pos = 0
    with project.db.session() as s:
        for e in events:
            assert e["timeline_in"]["frames"] == pos
            pos = e["timeline_out"]["frames"]
            segs = [
                s.get(Segment, int(ref[4:]))
                for ref in [e["segment_id"], *e["origin"]["merged_segments"]]
            ]
            assert all(g is not None for g in segs)
            seg = segs[0]
            assert seg is not None
            shot = s.get(Shot, seg.shot_id)
            assert shot is not None
            a, b = e["source_in"]["ticks"], e["source_out"]["ticks"]
            lo = min(g.usable_start_ticks for g in segs if g is not None)
            hi = max(g.usable_end_ticks for g in segs if g is not None)
            assert lo <= a < b <= hi
            assert shot.start_ticks <= a < b <= shot.end_ticks, "never across a shot cut"
        rejected = set(
            s.scalars(select(Disposition.segment_id).where(Disposition.status == "REJECT"))
        )
    assert not {int(e["segment_id"][4:]) for e in events} & rejected
    assert pos == v.timeline["duration"]["frames"]


def test_export_and_db_have_no_float_times(edited: tuple[Project, ControlDB, int]) -> None:
    project, _, edit_id = edited
    v = get_version(project, edit_id)
    path = export_path(project.workspace, edit_id, v.version)
    data = json.loads(path.read_text())
    assert data["timeline"] == v.timeline
    assert find_float_times(data) == []
    with project.db.session() as s:
        for row in s.scalars(select(EditVersion)):
            assert find_float_times(row.timeline) == []


def test_identical_request_makes_zero_ai_calls(edited: tuple[Project, ControlDB, int]) -> None:
    project, control, edit_id = edited
    before = len(fake.CALLS)
    again = _generate(project, control, EditRequest(duration_s=30))
    assert again == edit_id
    assert len(fake.CALLS) == before, "identical inputs: no AI call of any kind"
    with project.db.session() as s:
        versions = list(s.scalars(select(EditVersion).where(EditVersion.edit_id == edit_id)))
    assert len(versions) == 1, "identical key: no new version"
    take2 = _generate(project, control, EditRequest(duration_s=30, variant=1))
    assert take2 != edit_id
    assert len(fake.CALLS) == before + 2  # a fresh planner and selector take


def test_report_explains_every_event(edited: tuple[Project, ControlDB, int]) -> None:
    project, _, edit_id = edited
    r = report(project, edit_id)
    assert r["events"]
    for e in r["events"]:
        assert e["source_file"]
        assert e["reason"]
        assert e["role"]
        assert e["description"]
    codes = {c["code"] for x in r["rejected"]["items"] for c in x["reasons"]}
    assert "accidental_recording" in codes
    text = report_text(r)
    assert "blocking metrics: all zero" in text
    assert "Rejected segments" in text


def test_longer_edit_with_strict_chronology(analyzed_session: Any) -> None:
    project, control = analyzed_session
    edit_id = _generate(
        project, control, EditRequest(duration_s=60, chronology="strict", pace="energetic")
    )
    v = get_version(project, edit_id)
    assert v.metrics["blocking_ok"], (v.metrics, v.findings)


def test_edit_api(edited: tuple[Project, ControlDB, int]) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, control, edit_id = edited
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    listed = client.get(f"/api/projects/{project.id}/edits").json()["items"]
    mine = next(e for e in listed if e["display_id"] == f"edt_{edit_id:04d}")
    eid = mine["edit_id"]
    assert len(eid) == 26  # ULID
    body = client.get(f"/api/edits/{eid}").json()
    assert body["timeline"]["tracks"][0]["events"]
    assert find_float_times(body) == []
    versions = client.get(f"/api/edits/{eid}/versions").json()["items"]
    assert versions[0]["version"] == 1
    assert client.get(f"/api/edits/{eid}/versions/1").json()["version"] == 1
    rep = client.get(f"/api/edits/{eid}/report").json()
    assert rep["uid"] == eid
    assert rep["metrics"]["blocking_ok"]
    assert client.get("/api/edits/01ARZ3NDEKTSV4RRFFQ69G5FAV").status_code == 404
    assert client.get(f"/api/edits/{eid}/versions/99").status_code == 404
    bad = client.post(f"/api/projects/{project.id}/edits", json={"duration_s": 1})
    assert bad.status_code == 422


def test_selection_refs_are_unique_and_match(edited: tuple[Project, ControlDB, int]) -> None:
    project, _, edit_id = edited
    v = get_version(project, edit_id)
    events = v.timeline["tracks"][0]["events"]
    refs = [e["origin"]["selection_ref"] for e in events]
    assert len(refs) == len(set(refs))
    selections = v.timeline["selections"]
    for e in events:
        assert selections[e["origin"]["selection_ref"]]["segment_id"] == e["segment_id"]
        for ref, seg in zip(e["origin"]["merged"], e["origin"]["merged_segments"], strict=True):
            assert selections[ref]["segment_id"] == seg
            assert selections[ref]["used"] is True
    data = json.loads(export_path(project.workspace, edit_id, v.version).read_text())
    assert data["creator"] == "ai"
    assert data["key"] == v.key
    assert data["provenance_id"] == v.provenance_id
    assert export_path(project.workspace, edit_id, v.version).name == f"v{v.version:03d}.json"


def test_trip_context_changes_the_edit_but_never_reruns_vision(
    edited: tuple[Project, ControlDB, int],
) -> None:
    from mosaic.library.context import TripContext, save

    project, control, _ = edited
    request = EditRequest(duration_s=25, story="adventure_highlights")
    first = _generate(project, control, request)
    v1 = get_version(project, first)
    calls = list(fake.CALLS)
    with project.write() as s:
        save(s, TripContext(free_notes="An airshow; aircraft are the main subject."), "user")
    again = _generate(project, control, request)
    assert again == first
    v2 = get_version(project, first)
    assert v2.version == v1.version + 1, "a context change makes a new version"
    new_calls = fake.CALLS[len(calls) :]
    assert sorted(new_calls) == ["planner", "selector"], "context never re-runs vision"
    with project.write() as s:
        save(s, TripContext(), "user")  # leave the shared project as it was


def test_context_parse_job_proposes_without_saving(
    edited: tuple[Project, ControlDB, int],
) -> None:
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
    from mosaic.library.context import load

    project, control, _ = edited
    store = JobStore(control.db)
    job = LocalExecutor(store).submit(
        control.local_principal,
        JobSpec(
            project.id,
            "context",
            tasks=[
                TaskSpec(
                    "context.parse",
                    "context",
                    resource_class=ResourceClass.AI_API,
                    params={"text": "Airshow by the lake, the F-35 was the highlight."},
                )
            ],
        ),
    )
    assert run_job(control, job, timeout=120) == "done"
    proposal = store.tasks(job)[0].result["proposal"]
    assert "F-35" in proposal["free_notes"]
    assert store.job(job).result["proposal"] == proposal, "S7 reads it from GET /jobs/{id}"
    with project.db.session() as s:
        assert load(s).is_empty(), "nothing is saved until the owner confirms"
