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
from mosaic.editing.service import get_version, report, report_text
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Disposition, EditVersion, Segment, Shot
from mosaic.storage.projects import Project
from tests.support.editing import generate
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def edited(analyzed_session: Any) -> tuple[Project, ControlDB, int]:
    project, control = analyzed_session
    return project, control, generate(project, control, EditRequest(duration_s=30))


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
    again = generate(project, control, EditRequest(duration_s=30))
    assert again == edit_id
    assert len(fake.CALLS) == before, "identical inputs: no AI call of any kind"
    with project.db.session() as s:
        versions = list(s.scalars(select(EditVersion).where(EditVersion.edit_id == edit_id)))
    assert len(versions) == 1, "identical key: no new version"
    take2 = generate(project, control, EditRequest(duration_s=30, variant=1))
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
    edit_id = generate(
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
    first = generate(project, control, request)
    v1 = get_version(project, first)
    calls = list(fake.CALLS)
    with project.write() as s:
        save(s, TripContext(free_notes="An airshow; aircraft are the main subject."), "user")
    again = generate(project, control, request)
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


def test_report_lists_a_clip_the_owner_rejected(edited: tuple[Project, ControlDB, int]) -> None:
    """ADR 0042: never-include rejects every segment of the clip, analysed or not, as the
    owner's decision; resetting it gives the analysis back."""
    from sqlalchemy import select

    from mosaic.library import decisions
    from mosaic.storage.models_project import Segment

    project, _, edit_id = edited
    with project.db.session() as s:
        aid = s.scalars(select(Segment.asset_id).order_by(Segment.id)).first()
        n = len(list(s.scalars(select(Segment.id).where(Segment.asset_id == aid))))
    assert aid is not None
    before = report(project, edit_id)["rejected"]["total"]
    try:
        with project.write() as s:
            decisions.apply(s, [aid], {"include": "never"})
        r = report(project, edit_id)
        mine = [x for x in r["rejected"]["items"] if x["asset_id"] == f"ast_{aid:04d}"]
        assert len(mine) == n
        assert all(x["source"] == "user" for x in mine)
        assert all(x["whole_clip"] for x in mine)
        assert mine[0]["words"] == ["You rejected the whole clip"]
        assert mine[0]["source_file"]
    finally:
        with project.write() as s:
            decisions.apply(s, [aid], {"include": None})
    assert report(project, edit_id)["rejected"]["total"] == before


def test_edit_cards_presets_and_estimate(edited: tuple[Project, ControlDB, int]) -> None:
    """S13 cards and S14's presets, collages and estimate (ADR 0047)."""
    from fastapi.testclient import TestClient

    from mosaic.ai.adapters.fake import adapter as fake
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.models_project import EditVersion, SampleFrame

    project, control, edit_id = edited
    client = TestClient(create_app(Services.create(control)))
    client.app.state.allowed_hosts = {"testserver"}  # type: ignore[attr-defined]
    card = next(
        e
        for e in client.get(f"/api/projects/{project.id}/edits").json()["items"]
        if e["display_id"] == f"edt_{edit_id:04d}"
    )
    assert card["status"] in ("ready", "preview", "final")
    assert card["versions"] >= 1
    assert card["latest_version"] >= 1
    assert card["duration"]["frames"] > 0
    assert card["preliminary"] is False
    assert (card["aspect"], card["resolution"]) == ("16:9", "1080p")
    with project.db.session() as s:
        assert s.get(SampleFrame, card["cover_sample_id"]) is not None
    one = client.get(f"/api/projects/{project.id}/edits?limit=1").json()
    assert len(one["items"]) == 1
    if one["next_cursor"] is not None:
        rest = client.get(f"/api/projects/{project.id}/edits?cursor={one['next_cursor']}")
        assert one["items"][0]["edit_id"] not in {e["edit_id"] for e in rest.json()["items"]}

    cards = client.get(f"/api/projects/{project.id}/presets").json()["items"]
    assert [c["id"] for c in cards if c["featured"]][:2] == [
        "cinematic_journey",
        "chronological_diary",
    ]
    assert sum(c["featured"] for c in cards) == 7
    assert len(cards) == 16
    for preset in ("chronological_diary", "wildlife"):
        frames = client.get(f"/api/projects/{project.id}/presets/{preset}/collage").json()
        assert 1 <= len(frames["frames"]) <= 4
        assert len(set(frames["frames"])) == len(frames["frames"])
    assert client.get(f"/api/projects/{project.id}/presets/nope/collage").status_code == 404

    # The request that made this edit: the plan exists, so no cost; a new one is priced.
    with project.db.session() as s:
        v = s.query(EditVersion).filter(EditVersion.edit_id == edit_id).first()
        assert v is not None
        same = dict(v.request) | {"aspect": "9:16"}  # render-only: still the same plan
    calls = len(fake.CALLS)
    est = client.post("/api/edits/estimate", json={"project_id": project.id, "request": same})
    assert est.status_code == 200, est.text
    e = est.json()
    assert e["reuses_plan"] is True
    assert e["cost_usd"] == [0.0, 0.0]
    assert e["candidates"] > 0
    assert e["preliminary"] is False
    assert e["target"]["frames"] > 0
    assert isinstance(e["target"]["rate"], str)
    other = dict(same) | {"duration_s": 3600}
    e2 = client.post(
        "/api/edits/estimate", json={"project_id": project.id, "request": other}
    ).json()
    assert e2["reuses_plan"] is False
    assert e2["enough_footage"] is False
    assert e2["wall_seconds"][1] > e2["wall_seconds"][0] > 0
    assert len(fake.CALLS) == calls, "an estimate makes no AI call"
    bad = client.post("/api/edits/estimate", json={"project_id": project.id, "request": {}})
    assert bad.status_code == 422


def test_card_and_render_states_follow_their_jobs(
    edited: tuple[Project, ControlDB, int],
) -> None:
    """ADR 0047: a running edit job shows "generating"; a queued render "rendering"; a
    render whose job failed reads "failed" everywhere, so it can be re-rendered and not
    cancelled. No worker runs here: jobs stay queued until the test ends them."""
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.editing.service import submit_generate
    from mosaic.jobs.store import JobStore
    from mosaic.render.service import create_render, submit_render
    from mosaic.storage.models_control import Job

    project, control, edit_id = edited
    svc = Services.create(control)
    client = TestClient(create_app(svc))
    client.app.state.allowed_hosts = {"testserver"}  # type: ignore[attr-defined]
    store = JobStore(control.db)

    def card() -> dict[str, Any]:
        items = client.get(f"/api/projects/{project.id}/edits").json()["items"]
        return next(e for e in items if e["display_id"] == f"edt_{edit_id:04d}")

    def row(rid: int) -> dict[str, Any]:
        items = client.get(f"/api/projects/{project.id}/renders").json()["items"]
        return next(i for i in items if i["render_id"] == rid)

    assert card()["status"] == "ready"
    gen = submit_generate(svc.executor, control.local_principal, project, edit_id)
    assert card()["status"] == "generating"
    assert card()["pct"] == 0
    store.cancel(gen)
    assert card()["status"] == "ready"

    v = get_version(project, edit_id)
    rid = create_render(project, edit_id, v.version, "preview")
    job = submit_render(svc.executor, control.local_principal, project, rid)
    assert card()["status"] == "rendering"
    assert row(rid)["status"] == "queued"
    with control.db.session() as s, s.begin():
        j = s.get(Job, job)
        assert j is not None
        j.status, j.error = "failed", "encoder exploded"
    assert row(rid)["status"] == "failed"
    assert row(rid)["error"] == "encoder exploded"
    assert card()["status"] == "ready", "a failed render is not rendering"
    base = f"/api/projects/{project.id}/renders/{rid}"
    assert client.post(f"{base}/cancel").status_code == 409
    again = client.post(f"{base}/rerender")
    assert again.status_code == 202
    assert row(again.json()["render_id"])["status"] == "queued"
    store.cancel(again.json()["job_id"])
    assert row(again.json()["render_id"])["status"] == "cancelled"
    assert card()["status"] == "ready"
