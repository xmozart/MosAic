"""Edit generation on the analyzed synthetic corpus with the fake AI (M0 step 10)."""

from __future__ import annotations

import itertools
import json
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.core.timecheck import find_float_times
from mosaic.editing.generate import export_path
from mosaic.editing.request import EditRequest
from mosaic.editing.service import get_version, report, report_text
from mosaic.editing.titles import shot_events
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
    assert len(fake.CALLS) == before + 3  # a fresh planner and selector take, then the critic


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
    facts = body["facts"]  # S17 EditFacts (ADR 0049)
    assert facts["shots"] == len(shot_events(body["timeline"]["tracks"][0]["events"]))
    assert facts["duration"] == body["timeline"]["duration"]
    assert facts["target"]["frames"] == body["metrics"]["target_frames"]
    assert facts["beats"] == len(body["beats"])
    assert 0 <= facts["days_used"] <= facts["days_available"]  # fixture days may be unknown
    with project.db.session() as s:
        from mosaic.storage.models_project import Asset

        kinds = dict(s.query(Asset.id, Asset.kind).all())
    events = body["timeline"]["tracks"][0]["events"]
    assert facts["photos"] == sum(
        kinds[int(e["asset_id"][4:])] in ("photo", "live_photo") for e in events
    )
    assert isinstance(body["renders"], list)
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
    events = shot_events(v.timeline["tracks"][0]["events"])  # cards select nothing
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
    assert sorted(new_calls) == ["critic", "planner", "selector"], "context never re-runs vision"
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
    assert row(rid)["pct"] == 0, "S20: stopped before any shot was rendered"
    # Shots rendered before the failure: S20 says "Stopped at n %" (ADR 0050).
    from mosaic.storage.models_control import Task

    with control.db.session() as s, s.begin():
        tasks = list(s.query(Task).filter(Task.job_id == job).order_by(Task.id))
        for t in tasks[: len(tasks) // 3]:
            t.status = "done"
        stopped = 100 * (len(tasks) // 3) // len(tasks)
    assert stopped > 0
    assert row(rid)["pct"] == stopped
    assert card()["status"] == "ready", "a failed render is not rendering"
    base = f"/api/projects/{project.id}/renders/{rid}"
    assert client.post(f"{base}/cancel").status_code == 409
    again = client.post(f"{base}/rerender")
    assert again.status_code == 202
    assert row(again.json()["render_id"])["status"] == "queued"
    store.cancel(again.json()["job_id"])
    assert row(again.json()["render_id"])["status"] == "cancelled"
    assert card()["status"] == "ready"


def test_resolve_retimes_a_selection_without_ai(
    edited: tuple[Project, ControlDB, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deterministic half (M4 step 2a): the plan and selection a version was made
    from, turned into fresh shots and timed again, give the version's timeline, beats,
    findings and metrics, and make no AI call. Timing leaves its input shots unchanged."""
    import copy

    from mosaic.ai import client as ai_client
    from mosaic.editing import generate as gen
    from mosaic.editing import resolve as res

    project, control, _ = edited
    seen: dict[str, Any] = {}

    def shots_recording(plan: Any, sel: Any, by_ref: Any) -> Any:
        seen["plan"], seen["sel"], seen["by_ref"] = plan, sel, by_ref
        return res.shots_from_selection(plan, sel, by_ref)

    def resolve_recording(s: Any, req: Any, inp: Any, plan: Any, shots: Any, rejected: Any) -> Any:
        seen["req"], seen["inp"], seen["rejected"] = req, inp, rejected
        before = copy.deepcopy(shots)
        out = res.resolve(s, req, inp, plan, shots, rejected)
        assert shots == before, "resolve leaves its input shots as they were"
        return out

    monkeypatch.setattr(gen, "shots_from_selection", shots_recording)
    monkeypatch.setattr(gen, "resolve", resolve_recording)
    edit_id = generate(project, control, EditRequest(duration_s=20, variant=7))
    stored = get_version(project, edit_id)

    def no_ai(*_: Any, **__: Any) -> None:
        raise AssertionError("resolve called the AI")

    monkeypatch.setattr(ai_client.AIClient, "structured", no_ai)
    fresh = res.shots_from_selection(seen["plan"], seen["sel"], seen["by_ref"])
    with project.db.session() as s:
        again = res.resolve(s, seen["req"], seen["inp"], seen["plan"], fresh, seen["rejected"])
    assert again.timeline == stored.timeline
    assert again.beats == stored.beats
    # The AI critic's notes are added after timing (ADR 0082); the critic's own are equal.
    assert [f.as_json() for f in again.findings] == [
        f for f in stored.findings if f.get("source") != "ai"
    ]
    assert again.metrics == {
        k: v for k, v in stored.metrics.items() if k not in ("preliminary", "ai")
    }


def test_the_m4_request_reaches_the_plan(
    analyzed_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planner and selector v3 (ADR 0073): the owner's custom beats are the edit's beats,
    an avoided category stays out, and the prompts carry the preferences."""
    from mosaic.ai import client as ai_client

    project, control = analyzed_session
    sent: dict[str, Any] = {}
    real = ai_client.AIClient.structured

    def spying(
        self: Any, capability: str, name: str, version: int, ctx: Any, *a: Any, **k: Any
    ) -> Any:
        sent[name] = (version, ctx)
        return real(self, capability, name, version, ctx, *a, **k)

    monkeypatch.setattr(ai_client.AIClient, "structured", spying)
    req = EditRequest(
        duration_s=30,
        arc="custom",
        beats=["Arrival", "The middle", "Home"],
        weights={"conversations": "avoid", "landscapes": "more"},
    )
    edit_id = generate(project, control, req)
    v = get_version(project, edit_id)
    assert [b["title"] for b in v.beats] == ["Arrival", "The middle", "Home"]
    assert sent["planner"][0] == 3
    assert "Avoid: conversations." in sent["planner"][1]["preferences"]
    assert "exactly these 3" in sent["planner"][1]["arc"]
    assert sent["selector"][0] == 3
    assert "More of: landscapes." in sent["selector"][1]["preferences"]
    picked = {sel["segment_id"] for sel in v.timeline["selections"].values() if sel.get("used")}
    with project.db.session() as s:
        speech = {
            f"seg_{sid:06d}"
            for sid in s.scalars(select(Segment.id).where(Segment.has_speech.is_(True)))
        }
    assert not picked & speech, "the avoided category stays out"


def test_photos_become_stills(analyzed_session: Any) -> None:
    """M4 step 6 (ADR 0075): with photo share "many", the corpus's photo is a still event
    of 2–5 s, silent, with its pan and zoom; with "none" there is no still."""
    project, control = analyzed_session
    # Long enough that the solver drops nothing: the fake selector's photo pick is the
    # last of its beat, the first to go when an edit must shrink.
    edit_id = generate(project, control, EditRequest(duration_s=600, photo_share="many"))
    events = get_version(project, edit_id).timeline["tracks"][0]["events"]
    stills = [e for e in events if e["kind"] == "still"]
    assert stills, [e["kind"] for e in events]
    rate = Fraction(30000, 1001)
    for e in stills:
        frames = e["timeline_out"]["frames"] - e["timeline_in"]["frames"]
        assert 2 * rate - 1 <= frames <= 5 * rate + 1
        assert e["duration"]["frames"] == frames
        assert e["audio"]["source_enabled"] is False
        assert set(e["motion"]) == {"start", "end", "easing"}
    none = generate(project, control, EditRequest(duration_s=600, photo_share="none"))
    kinds = {e["kind"] for e in get_version(project, none).timeline["tracks"][0]["events"]}
    assert kinds == {"video"}


def test_analysis_finds_each_segments_subject_and_edits_carry_it(analyzed_session: Any) -> None:
    """ADR 0076: the focus stage gives every analysed segment a subject position in
    thousandths of the frame; an edit's events carry it in their transform."""
    project, control = analyzed_session
    with project.db.session() as s:
        points = list(s.execute(select(Segment.focus_x, Segment.focus_y)))
    assert points
    assert all(x is not None and y is not None for x, y in points)
    assert all(0 <= x <= 1000 and 0 <= y <= 1000 for x, y in points)
    edit_id = generate(project, control, EditRequest(duration_s=25, variant=41))
    events = get_version(project, edit_id).timeline["tracks"][0]["events"]
    assert all("focus" in e["transform"] for e in events)


def test_dialogue_gets_j_and_l_cuts_without_cutting_a_word(analyzed_session: Any) -> None:
    """M4 step 8 (ADR 0077): at each boundary between the corpus's speech clip and another
    recording, the picture cut moves by up to 1 s while the sound stays on whole
    sentences, unless the neighbour has no picture to spare. Sound and picture each cover
    the edit exactly, and nothing heard starts or ends in a word."""
    project, control = analyzed_session
    edit_id = generate(
        project, control, EditRequest(duration_s=60, weights={"conversations": "strong"})
    )
    v = get_version(project, edit_id)
    events = v.timeline["tracks"][0]["events"]
    one_s, smallest = 29, 6  # whole frames at 29.97
    pos = 0
    for e in events:
        a = e["audio"].get("timeline_in", e["timeline_in"])["frames"]
        b = e["audio"].get("timeline_out", e["timeline_out"])["frames"]
        assert a == pos
        pos = b
        assert abs(a - e["timeline_in"]["frames"]) <= one_s
        assert abs(b - e["timeline_out"]["frames"]) <= one_s
    assert pos == v.timeline["duration"]["frames"]
    assert v.metrics["mid_word_cuts"] == 0
    assert v.metrics["dialogue_truncations"] == 0

    def talks(e: dict[str, Any]) -> bool:
        return bool(e["audio"].get("intent") == "dialogue")

    checked = 0
    with project.db.session() as s:
        for x, y in itertools.pairwise(events):
            if talks(x) == talks(y) or x["asset_id"] == y["asset_id"]:
                continue
            if x["origin"]["locked"] or y["origin"]["locked"] or "still" in (x["kind"], y["kind"]):
                continue
            checked += 1
            offset = (
                y["audio"].get("timeline_in", y["timeline_in"])["frames"]
                - y["timeline_in"]["frames"]
            )
            if offset:
                assert x["audio"]["timeline_out"]["frames"] == y["audio"]["timeline_in"]["frames"]
                continue
            # No split: the speaker is too short, or the neighbour had no picture to spare
            # on the speaker's side.
            other, later = (x, True) if talks(y) else (y, False)
            speaker = y if later else x
            frames = speaker["timeline_out"]["frames"] - speaker["timeline_in"]["frames"]
            if min(frames // 4, frames - 45) < smallest:  # balanced pace: 45 frames minimum
                continue
            seg = s.get(Segment, int(other["segment_id"][4:]))
            assert seg is not None
            room = (
                seg.usable_end_ticks - other["source_out"]["ticks"]
                if later
                else other["source_in"]["ticks"] - seg.usable_start_ticks
            )
            assert room < smallest * 3003, (other["event_id"], room)
    assert checked, "the edit has a dialogue boundary"


def test_the_ai_critic_reviews_a_generated_cut_by_event_id(
    analyzed_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4 step 10b (ADR 0082): after a generation the AI critic reads the cut as text and
    its notes, about shots by event id, become findings with source "ai"; a "remove" is
    applied like any fix. Off by the setting, or failing, the edit is made without it."""
    from mosaic.ai.adapters.fake.adapter import RESPONDERS
    from mosaic.editing import findings
    from mosaic.storage.config import ConfigService

    project, control = analyzed_session
    before = fake.CALLS.count("critic")
    edit_id = generate(project, control, EditRequest(duration_s=40, variant=23))
    assert fake.CALLS.count("critic") == before + 1
    v = get_version(project, edit_id)
    events = v.timeline["tracks"][0]["events"]
    shots = [e for e in events if e["kind"] != "title"]
    ai = [f for f in v.findings if f.get("source") == "ai"]
    assert [f["code"] for f in ai] == ["ai_note", "ai_remove"]
    note, remove = ai
    assert note["event_id"] == shots[0]["event_id"]
    assert "ops" not in note, "a note has nothing to apply"
    victim = shots[-2]
    assert remove["event_id"] == victim["event_id"]
    assert remove["frame"] == victim["timeline_in"]["frames"]
    assert remove["ops"] == [{"kind": "remove_shot", "ref": victim["origin"]["selection_ref"]}]
    assert v.metrics["ai"]["critic"]["provider"] == "fake"
    with project.db.session() as s:
        rows = findings.of_version(s, edit_id, v.version)
        uid = next(f.uid for f in rows if f.code == "ai_remove")
        assert {f.source for f in rows if f.code.startswith("ai_")} == {"ai"}
    child, skipped = findings.apply(project, edit_id, [uid])
    assert skipped == []
    after = get_version(project, edit_id, child)
    refs = {e["origin"].get("selection_ref") for e in after.timeline["tracks"][0]["events"]}
    assert victim["origin"]["selection_ref"] not in refs

    # A critic that names a shot not in the cut is retried, then left out: the edit stands.
    def wrong(request: Any) -> dict[str, Any]:
        return {
            "notes": [
                {
                    "event_id": "evt_9999",
                    "action": "remove",
                    "severity": "warning",
                    "text": "This shot is not in the cut at all.",
                }
            ]
        }

    monkeypatch.setitem(RESPONDERS, "critic", wrong)
    broken = generate(project, control, EditRequest(duration_s=40, variant=24))
    bv = get_version(project, broken)
    assert "skipped" in bv.metrics["ai"]["critic"]
    assert not [f for f in bv.findings if f.get("source") == "ai"]

    config = ConfigService(control)
    config.set(control.local_principal, "editing.ai_critic", False)
    try:
        calls = fake.CALLS.count("critic")
        off = generate(project, control, EditRequest(duration_s=40, variant=25))
        assert fake.CALLS.count("critic") == calls
        assert "critic" not in get_version(project, off).metrics["ai"]
    finally:
        config.set(control.local_principal, "editing.ai_critic", True)


def test_the_estimate_counts_the_ai_critics_call_when_it_is_on(analyzed_session: Any) -> None:
    """ADR 0082: a new plan takes the planner, the selector and, when it is on, the
    critic: three calls of wall time, two without it."""
    from mosaic.editing import estimate
    from mosaic.storage.config import ConfigService

    project, control = analyzed_session
    config = ConfigService(control)
    me = control.local_principal
    req = EditRequest(duration_s=55, variant=31)  # never generated: no plan to reuse
    with project.db.session() as s:
        on = estimate.for_request(s, config, me, project.id, req)
        config.set(me, "editing.ai_critic", False)
        try:
            off = estimate.for_request(s, config, me, project.id, req)
        finally:
            config.set(me, "editing.ai_critic", True)
    assert not on["reuses_plan"]
    assert on["wall_seconds"][0] == 3 * estimate.CALL_SECONDS[0]
    assert off["wall_seconds"][0] == 2 * estimate.CALL_SECONDS[0]


def test_a_generation_reports_its_steps_and_beats_for_s15(analyzed_session: Any) -> None:
    """ADR 0087: the job's result carries S15's live view - the step, moments and
    candidates, and the plan's beats with frames of each beat's first shots."""
    from mosaic.editing.service import create_edit, submit_generate
    from mosaic.storage.models_project import SampleFrame

    project, control = analyzed_session
    store = JobStore(control.db)
    edit_id = create_edit(
        project, EditRequest(duration_s=40, variant=47), control, control.local_principal
    )
    job = submit_generate(LocalExecutor(store), control.local_principal, project, edit_id)
    assert run_job(control, job, timeout=600) == "done"
    row = store.job(job)
    assert row is not None
    creating = row.result["creating"]
    assert creating["step"] == "checking", "the last step it reached before the version"
    assert creating["moments"] >= creating["candidates"] > 0
    v = get_version(project, edit_id)
    assert [b["title"] for b in creating["beats"]] == [b["title"] for b in v.beats]
    framed = [sid for b in creating["beats"] for sid in b["sample_ids"]]
    assert framed, "beats show frames of their first shots"
    assert all(len(b["sample_ids"]) <= 3 for b in creating["beats"])
    with project.db.session() as s:
        assert all(s.get(SampleFrame, sid) is not None for sid in framed)
