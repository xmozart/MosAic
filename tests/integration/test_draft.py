"""An edit's draft over the API (S16; ADR 0067), on the analyzed synthetic corpus with
the fake AI: the storyboard, undoable ops, saving a version and rendering the draft."""

from __future__ import annotations

from typing import Any

import pytest

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.editing.request import EditRequest
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import Project
from tests.support.editing import generate

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def drafted(analyzed_session: Any) -> tuple[Project, ControlDB, Any, str]:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, control = analyzed_session
    edit_id = generate(project, control, EditRequest(duration_s=30, variant=11))
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    listed = client.get(f"/api/projects/{project.id}/edits").json()["items"]
    eid = next(e for e in listed if e["display_id"] == f"edt_{edit_id:04d}")["edit_id"]
    return project, control, client, eid


def _shots(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [sh for b in d["board"]["beats"] for sh in b["shots"]]


def test_an_untouched_draft_times_exactly_like_its_version(drafted: Any) -> None:
    _, _, client, eid = drafted
    calls = len(fake.CALLS)
    d = client.get(f"/api/edits/{eid}/draft").json()
    version = client.get(f"/api/edits/{eid}").json()
    assert not d["dirty"]
    assert not d["can_undo"]
    assert not d["can_redo"]
    assert d["base_version"] == version["version"]
    assert d["timeline"] == version["timeline"]
    assert d["duration"] == version["timeline"]["duration"]
    assert version["draft"]["dirty"] is False
    assert [b["beat_id"] for b in d["board"]["beats"]] == [b["beat_id"] for b in version["beats"]]
    assert len(fake.CALLS) == calls, "the draft is timed without AI"


def test_ops_undo_redo_and_saving_a_version(drafted: Any) -> None:
    project, _, client, eid = drafted
    calls = len(fake.CALLS)
    start = client.get(f"/api/edits/{eid}/draft").json()
    beats = start["board"]["beats"]
    first = beats[0]["shots"][0]["ref"]

    locked = client.post(
        f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": first}}
    )
    assert locked.status_code == 200, locked.text
    d = locked.json()
    assert d["dirty"]
    assert d["can_undo"]
    assert next(sh for sh in _shots(d) if sh["ref"] == first)["locked"]
    events = d["timeline"]["tracks"][0]["events"]
    assert any(e["origin"]["selection_ref"] == first and e["origin"]["locked"] for e in events)

    refused = client.post(
        f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "remove_shot", "ref": first}}
    )
    assert refused.status_code == 422
    assert "locked" in refused.text
    bad = client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "trim"}})
    assert bad.status_code == 422

    target = beats[-1]["beat_id"]
    moved = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "move_shot", "ref": first, "beat_id": target, "index": 0}},
    ).json()
    assert moved["board"]["user_order"]
    assert moved["board"]["beats"][-1]["shots"][0]["ref"] == first
    assert moved["ops"] == 2

    undone = client.post(f"/api/edits/{eid}/draft/undo").json()
    assert undone["ops"] == 1
    assert undone["can_redo"]
    assert not undone["board"]["user_order"]
    redone = client.post(f"/api/edits/{eid}/draft/redo").json()
    assert redone["board"] == moved["board"]
    assert not redone["can_redo"]
    client.post(f"/api/edits/{eid}/draft/undo")
    # A new op drops what was undone.
    other = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "move_beat", "beat_id": target, "index": 0}},
    ).json()
    assert not other["can_redo"]
    assert other["board"]["beats"][0]["beat_id"] == target

    saved = client.post(f"/api/edits/{eid}/versions")
    assert saved.status_code == 201, saved.text
    v = saved.json()
    assert v["version"] == start["base_version"] + 1
    assert v["parent_version"] == start["base_version"]
    assert v["creator"] == "user"
    assert v["timeline"] == other["timeline"]
    assert (project.workspace / "edits" / v["display_id"] / f"v{v['version']:03d}.json").is_file()
    after = client.get(f"/api/edits/{eid}/draft").json()
    assert not after["dirty"]
    assert after["base_version"] == v["version"]
    assert after["board"] == other["board"], "the new version's storyboard is the draft's"
    assert after["timeline"] == v["timeline"]
    assert client.post(f"/api/edits/{eid}/versions").status_code == 409
    assert len(fake.CALLS) == calls, "drafts make no AI call"


def test_rendering_a_changed_draft_saves_a_version_first(drafted: Any) -> None:
    _, _, client, eid = drafted
    d = client.get(f"/api/edits/{eid}/draft").json()
    ref = d["board"]["beats"][0]["shots"][0]["ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}})
    started = client.post(f"/api/edits/{eid}/preview")
    assert started.status_code == 202, started.text
    assert started.json()["version"] == d["base_version"] + 1
    version = client.get(f"/api/edits/{eid}").json()
    assert version["creator"] == "system"
    assert version["reason"] == "Saved before render"
    assert not version["draft"]["dirty"]


def _fresh(
    drafted: Any, variant: int, seconds: int = 30
) -> tuple[Project, ControlDB, Any, int, str]:
    project, control, client, _ = drafted
    edit_id = generate(project, control, EditRequest(duration_s=seconds, variant=variant))
    listed = client.get(f"/api/projects/{project.id}/edits").json()["items"]
    eid = next(e for e in listed if e["display_id"] == f"edt_{edit_id:04d}")["edit_id"]
    return project, control, client, edit_id, eid


def _in_edit(d: dict[str, Any]) -> set[str]:
    return {
        ref
        for e in d["timeline"]["tracks"][0]["events"]
        for ref in (e["segment_id"], *e["origin"]["merged_segments"])
    }


def test_what_the_owner_took_out_never_comes_back(drafted: Any) -> None:
    """A replaced or removed segment is not brought back as a spare, even when the draft
    runs short and the solver backfills from alternatives."""
    _, _, client, _, eid = _fresh(drafted, 12)
    d = client.get(f"/api/edits/{eid}/draft").json()
    shots = _shots(d)
    swap = next(sh for sh in shots if sh["alternatives"])
    taken = {swap["segment_id"]}
    d = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={
            "op": {
                "kind": "replace_shot",
                "ref": swap["ref"],
                "segment_id": swap["alternatives"][0]["segment_id"],
            }
        },
    ).json()
    for sh in [sh for sh in _shots(d) if sh["ref"] != swap["ref"]][: len(shots) // 2]:
        taken.add(sh["segment_id"])
        d = client.post(
            f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "remove_shot", "ref": sh["ref"]}}
        ).json()
    assert d["board"]["excluded"] == sorted(taken)
    assert not taken & _in_edit(d)
    assert d["metrics"]["solver"]["notes"] or d["duration"]["frames"] <= d["target"]["frames"]
    saved = client.post(f"/api/edits/{eid}/versions").json()
    assert saved["timeline"]["excluded"] == sorted(taken)
    after = client.get(f"/api/edits/{eid}/draft").json()
    assert after["board"]["excluded"] == sorted(taken), "the exclusions outlive the save"
    assert not taken & _in_edit(after)


def test_the_owners_order_holds_even_when_backfilling(drafted: Any) -> None:
    _, _, client, _, eid = _fresh(drafted, 13)
    d = client.get(f"/api/edits/{eid}/draft").json()
    beats = [b["beat_id"] for b in d["board"]["beats"]]
    d = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "move_beat", "beat_id": beats[-1], "index": 0}},
    ).json()
    for sh in _shots(d)[1::2]:  # make it short, so the solver backfills
        d = client.post(
            f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "remove_shot", "ref": sh["ref"]}}
        ).json()
    order = [b["beat_id"] for b in d["board"]["beats"]]
    seen = [e["beat_id"] for e in d["timeline"]["tracks"][0]["events"]]
    assert seen == sorted(seen, key=order.index), "beats play in the storyboard's order"


def test_an_older_version_without_a_storyboard_still_drafts(drafted: Any) -> None:
    """Versions from before M4 have no ``beats[].shots`` nor ``timeline.order``: the
    storyboard is rebuilt from their selections and times exactly like them."""
    from mosaic.editing.draft import board_of
    from mosaic.storage.models_project import EditVersion

    project, _, client, edit_id, eid = _fresh(drafted, 14)
    with project.write() as s:
        row = s.query(EditVersion).filter_by(edit_id=edit_id).one()
        full = board_of(row)
        row.beats = [{k: v for k, v in b.items() if k != "shots"} for b in row.beats]
        row.timeline = {k: v for k, v in row.timeline.items() if k != "order"}
        old = board_of(row)
    assert old == full
    stored = client.get(f"/api/edits/{eid}").json()
    d = client.get(f"/api/edits/{eid}/draft").json()
    assert {k: v for k, v in d["timeline"].items() if k != "order"} == stored["timeline"]


def test_ops_on_an_older_version_are_stale(drafted: Any) -> None:
    from mosaic.editing import draft
    from mosaic.editing.service import save_draft
    from mosaic.storage.models_project import EditDraftOp

    project, _, client, edit_id, eid = _fresh(drafted, 15)
    ref = _shots(client.get(f"/api/edits/{eid}/draft").json())[0]["ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}})
    client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "lock_shot", "ref": ref, "locked": False}},
    )
    client.post(f"/api/edits/{eid}/draft/undo")
    # A version made elsewhere (the CLI's own draft save, as rendering does) while
    # these ops stay in the table on the old base.
    with project.write() as s:
        s.add(
            EditDraftOp(
                edit_id=edit_id,
                base_version=1,
                seq=99,
                op={"kind": "lock_shot", "ref": ref, "locked": True},
                undone=False,
                created_at="x",
            )
        )
    assert save_draft(project, edit_id) == 2
    with project.write() as s:
        s.add(
            EditDraftOp(
                edit_id=edit_id,
                base_version=1,
                seq=100,
                op={"kind": "remove_shot", "ref": ref},
                undone=False,
                created_at="x",
            )
        )
    with project.db.session() as s:
        d = draft.load(s, edit_id)
        assert d.base.version == 2
        assert not d.dirty, "ops on version 1 no longer count"
        assert not draft.undo(s, edit_id)
    later = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "lock_shot", "ref": ref, "locked": False}},
    )
    assert later.status_code == 200, later.text
    with project.db.session() as s:
        rows = list(s.query(EditDraftOp).filter_by(edit_id=edit_id))
    assert [r.base_version for r in rows] == [2], "the stale rows are dropped"
    assert len({r.seq for r in rows}) == len(rows)


def test_render_and_regenerate_save_a_changed_draft_first(drafted: Any) -> None:
    """The rule the API and ``mosaic render`` share (``version_to_render``), and
    regenerating, which must not lose unsaved changes."""
    from mosaic.editing.service import submit_generate
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.render.service import version_to_render

    project, control, client, edit_id, eid = _fresh(drafted, 16)
    ref = _shots(client.get(f"/api/edits/{eid}/draft").json())[0]["ref"]
    assert version_to_render(project, edit_id, None) == 1, "nothing to save"
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}})
    assert version_to_render(project, edit_id, 1) == 1, "an explicit version saves nothing"
    assert client.get(f"/api/edits/{eid}").json()["draft"]["dirty"]
    assert version_to_render(project, edit_id, None) == 2
    v2 = client.get(f"/api/edits/{eid}").json()
    assert (v2["creator"], v2["reason"]) == ("system", "Saved before render")
    client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "lock_shot", "ref": ref, "locked": False}},
    )
    submit_generate(LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id)
    v3 = client.get(f"/api/edits/{eid}/versions/3").json()
    assert (v3["creator"], v3["reason"]) == ("system", "Saved before regenerate")


def test_a_locked_shot_keeps_its_cut_through_later_changes(drafted: Any) -> None:
    """M4 step 3a (ADR 0068): locking records the shot's cut, and later ops, saves and
    re-timings keep its source range and frames exactly."""
    _, _, client, _, eid = _fresh(drafted, 17)
    d = client.get(f"/api/edits/{eid}/draft").json()
    events = d["timeline"]["tracks"][0]["events"]
    e = events[len(events) // 2]
    ref = e["origin"]["selection_ref"]
    before = (
        e["source_in"],
        e["source_out"],
        e["timeline_out"]["frames"] - e["timeline_in"]["frames"],
    )
    sneaky = {
        "segment_id": next(s for s in _shots(d) if s["ref"] == ref)["segment_id"],
        "source_in": {"ticks": 0, "tb": before[0]["tb"]},
        "source_out": {"ticks": 1, "tb": before[0]["tb"]},
        "duration": {"frames": 1, "rate": d["timeline"]["rate"]},
    }  # the server's pin wins
    d = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "lock_shot", "ref": ref, "pin": sneaky}},
    ).json()
    sh = next(s for s in _shots(d) if s["ref"] == ref)
    assert sh["pin"] == {
        "segment_id": sh["segment_id"],
        "source_in": before[0],
        "source_out": before[1],
        "duration": {"frames": before[2], "rate": d["timeline"]["rate"]},
    }
    absorbed = [s["ref"] for s in _shots(d) if s["absorbed_by"] == ref]
    locked_event = next(
        x for x in d["timeline"]["tracks"][0]["events"] if x["origin"]["selection_ref"] == ref
    )
    assert locked_event["origin"]["merged"] == absorbed
    for other in [s for s in _shots(d) if s["ref"] != ref and not s["absorbed_by"]][:3]:
        d = client.post(
            f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "remove_shot", "ref": other["ref"]}}
        ).json()
    saved = client.post(f"/api/edits/{eid}/versions").json()
    after = next(
        x for x in saved["timeline"]["tracks"][0]["events"] if x["origin"]["selection_ref"] == ref
    )
    assert (
        after["source_in"],
        after["source_out"],
        after["timeline_out"]["frames"] - after["timeline_in"]["frames"],
    ) == before
    assert after["origin"]["locked"]
    assert saved["metrics"]["locks"]["frames"] >= before[2]
    unlocked = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "lock_shot", "ref": ref, "locked": False}},
    ).json()
    assert next(s for s in _shots(unlocked) if s["ref"] == ref)["pin"] is None


def test_regenerating_a_beat_keeps_three_locked_shots_where_they_were(drafted: Any) -> None:
    """M4 acceptance 2 (ADR 0069): the owner locks 3 shots and regenerates their beat; the
    locked shots keep their cut and their slot in the beat, the rest is a fresh take."""
    from tests.support.runner import run_job

    _, control, client, _, eid = _fresh(drafted, 18, 60)
    d = client.get(f"/api/edits/{eid}/draft").json()
    in_edit = {e["origin"]["selection_ref"] for e in d["timeline"]["tracks"][0]["events"]}
    beat = max(d["board"]["beats"], key=lambda b: sum(s["ref"] in in_edit for s in b["shots"]))
    lockable = [s["ref"] for s in beat["shots"] if s["ref"] in in_edit and not s["absorbed_by"]]
    assert len(lockable) >= 3, beat
    assert len(set(beat["pool"])) > len(beat["shots"]), "room for a different take"
    chosen = lockable[:1] + lockable[-2:]  # the first and the last two: free slots between
    for ref in chosen:
        d = client.post(
            f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}}
        ).json()
    before = next(b for b in d["board"]["beats"] if b["beat_id"] == beat["beat_id"])
    slots = {s["ref"]: i for i, s in enumerate(before["shots"])}
    pins = {s["ref"]: s["pin"] for s in before["shots"] if s["ref"] in chosen}
    others = [b for b in d["board"]["beats"] if b["beat_id"] != beat["beat_id"]]
    vision = fake.CALLS.count("vision")

    started = client.post(f"/api/edits/{eid}/beats/{beat['beat_id']}/regenerate")
    assert started.status_code == 202, started.text
    assert run_job(control, started.json()["job_id"]) == "done"

    v = client.get(f"/api/edits/{eid}").json()
    assert v["creator"] == "ai"
    assert v["reason"].startswith("Regenerated")
    assert v["parent_version"] == d["base_version"] + 1, "the locks were saved first"
    after = client.get(f"/api/edits/{eid}/draft").json()
    beat_after = next(b for b in after["board"]["beats"] if b["beat_id"] == beat["beat_id"])
    for ref in chosen:
        i = next(i for i, s in enumerate(beat_after["shots"]) if s["ref"] == ref)
        assert i == slots[ref], f"{ref} keeps its slot in the beat"
        assert beat_after["shots"][i]["pin"] == pins[ref], f"{ref} keeps its cut"
    events = v["timeline"]["tracks"][0]["events"]
    for ref in chosen:
        e = next(e for e in events if e["origin"]["selection_ref"] == ref)
        pin = pins[ref]
        assert e["source_in"] == pin["source_in"]
        assert e["source_out"] == pin["source_out"]
        assert e["timeline_out"]["frames"] - e["timeline_in"]["frames"] == pin["duration"]["frames"]
        assert e["origin"]["locked"]
    order = [e["origin"]["selection_ref"] for e in events if e["origin"]["selection_ref"] in chosen]
    assert order == sorted(chosen, key=slots.__getitem__), "the same relative order"
    assert [b for b in after["board"]["beats"] if b["beat_id"] != beat["beat_id"]] == others
    assert fake.CALLS.count("vision") == vision, "no vision call"
    free_before = {s["segment_id"] for s in before["shots"] if s["ref"] not in chosen}
    free_after = {s["segment_id"] for s in beat_after["shots"] if s["ref"] not in chosen}
    assert free_after, "the free slots are filled again"
    assert free_after != free_before, "a fresh take"
    assert after["board"]["excluded"] == d["board"]["excluded"]
    assert after["board"]["user_order"] == d["board"]["user_order"]
    assert after["regenerating"] == []


def test_regenerating_a_beat_with_every_shot_locked_is_refused(drafted: Any) -> None:
    _, _, client, _, eid = _fresh(drafted, 19)
    d = client.get(f"/api/edits/{eid}/draft").json()
    beat = d["board"]["beats"][0]
    for sh in beat["shots"]:
        if not sh["absorbed_by"]:
            client.post(
                f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": sh["ref"]}}
            )
    versions = len(client.get(f"/api/edits/{eid}/versions").json()["items"])
    refused = client.post(f"/api/edits/{eid}/beats/{beat['beat_id']}/regenerate")
    assert refused.status_code == 422
    assert "locked" in refused.text
    assert client.post(f"/api/edits/{eid}/beats/b99/regenerate").status_code == 404
    assert len(client.get(f"/api/edits/{eid}/versions").json()["items"]) == versions, (
        "a refused regenerate saves nothing"
    )
    assert client.get(f"/api/edits/{eid}/draft").json()["dirty"]


def test_each_regeneration_is_a_fresh_take(drafted: Any) -> None:
    from tests.support.runner import run_job

    _, control, client, _, eid = _fresh(drafted, 20, 37)
    beat = client.get(f"/api/edits/{eid}/draft").json()["board"]["beats"][0]["beat_id"]
    calls = fake.CALLS.count("reselect")
    for _ in range(2):
        job = client.post(f"/api/edits/{eid}/beats/{beat}/regenerate").json()["job_id"]
        assert run_job(control, job) == "done"
        v = client.get(f"/api/edits/{eid}").json()
        assert v["metrics"]["ai"]["selector"]["cached"] is False
    assert fake.CALLS.count("reselect") == calls + 2
    assert v["metrics"]["regenerated"]["take"] == 2


def test_a_change_made_while_the_ai_answers_is_kept(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S16 keeps the other beats editable while one regenerates: an op that lands during
    the AI call is saved, and the take is redone from the cache, not asked again."""
    from mosaic.ai import client as ai_client
    from mosaic.editing.draft import LockShot
    from mosaic.editing.service import change_draft
    from tests.support.runner import run_job

    project, control, client, edit_id, eid = _fresh(drafted, 21, 41)
    d = client.get(f"/api/edits/{eid}/draft").json()
    beat = d["board"]["beats"][0]["beat_id"]
    other = next(
        sh["ref"] for b in d["board"]["beats"][1:] for sh in b["shots"] if not sh["absorbed_by"]
    )
    real = ai_client.AIClient.structured
    landed: list[bool] = []

    def racing(self: Any, *args: Any, **kwargs: Any) -> Any:
        out = real(self, *args, **kwargs)
        if not landed:
            change_draft(project, edit_id, "op", LockShot(ref=other))
            landed.append(True)
        return out

    monkeypatch.setattr(ai_client.AIClient, "structured", racing)
    calls = fake.CALLS.count("reselect")
    job = client.post(f"/api/edits/{eid}/beats/{beat}/regenerate").json()["job_id"]
    assert run_job(control, job) == "done"
    v = client.get(f"/api/edits/{eid}").json()
    assert v["reason"].startswith("Regenerated")
    kept = next(sh for b in v["beats"] for sh in b["shots"] if sh["ref"] == other)
    assert kept["locked"], "the owner's change is kept"
    assert landed, "the op landed during the AI call"
    assert fake.CALLS.count("reselect") == calls + 1, "the redo replays the cache"


def test_regenerating_the_edit_or_its_story_keeps_the_locks(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRODUCT.md §8 (ADR 0070): the whole edit, or the story from the edit's own clips,
    regenerated with the owner's locked shots kept, cut and all."""
    from mosaic.ai import client as ai_client
    from tests.support.runner import run_job

    _, control, client, _, eid = _fresh(drafted, 22, 43)
    d = client.get(f"/api/edits/{eid}/draft").json()
    in_edit = [e["origin"]["selection_ref"] for e in d["timeline"]["tracks"][0]["events"]]
    chosen = in_edit[:2]
    for ref in chosen:
        d = client.post(
            f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}}
        ).json()
    pins = {s["ref"]: s["pin"] for s in _shots(d) if s["ref"] in chosen}
    variants: list[int] = []
    real = ai_client.AIClient.structured

    def spying(self: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
        if capability == "planner":
            variants.append(kwargs["variant"])
        return real(self, capability, *args, **kwargs)

    monkeypatch.setattr(ai_client.AIClient, "structured", spying)
    for scope in ("all", "story"):
        before = client.get(f"/api/edits/{eid}/draft").json()
        clips_before = {s["segment_id"] for s in _shots(before)}
        started = client.post(f"/api/edits/{eid}/regenerate", params={"scope": scope})
        assert started.status_code == 202, started.text
        queued = client.get(f"/api/edits/{eid}/draft").json()
        assert queued["regenerating_scope"] == scope, "a reload shows it running"
        assert run_job(control, started.json()["job_id"]) == "done"
        v = client.get(f"/api/edits/{eid}").json()
        assert v["creator"] == "ai"
        assert v["metrics"]["regenerated"]["scope"] == scope
        after = client.get(f"/api/edits/{eid}/draft").json()
        assert after["regenerating_scope"] is None
        kept = {s["ref"]: s for s in _shots(after) if s["ref"] in chosen}
        assert set(kept) == set(chosen)
        assert all(kept[r]["locked"] and kept[r]["pin"] == pins[r] for r in chosen)
        events = {e["origin"]["selection_ref"]: e for e in v["timeline"]["tracks"][0]["events"]}
        for r in chosen:
            assert events[r]["source_in"] == pins[r]["source_in"]
            assert events[r]["source_out"] == pins[r]["source_out"]
        if scope == "story":
            assert {s["segment_id"] for s in _shots(after)} <= clips_before, "no new clips"
    assert client.post(f"/api/edits/{eid}/regenerate", params={"scope": "beat"}).status_code == 422
    assert client.post(f"/api/edits/{eid}/regenerate").status_code == 422, "scope is required"
    assert len(variants) == 2
    assert len(set(variants)) == 2, "a story take and an edit take never share an answer"
    assert all(v < 0 for v in variants), "never an edit's own --variant"
