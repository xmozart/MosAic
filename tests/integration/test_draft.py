"""An edit's draft over the API (S16; ADR 0067), on the analyzed synthetic corpus with
the fake AI: the storyboard, undoable ops, saving a version and rendering the draft."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

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


def test_the_storyboard_shows_each_shots_frame_file_and_day(drafted: Any) -> None:
    """S16's chips (ADR 0088): a frame inside the shot, its file, day, asset and usable
    range, for every shot on the board; and the target's tolerance in frames."""
    project, _, client, eid = drafted
    d = client.get(f"/api/edits/{eid}/draft").json()
    segments = {sh["segment_id"] for sh in _shots(d)}
    assert set(d["media"]) == segments
    for ref, m in d["media"].items():
        assert isinstance(m["sample_id"], int), ref
        assert m["file"]
        assert "/" not in m["file"]
        assert isinstance(m["asset"], int)
        assert m["range"]["start"]["tb"] == m["range"]["end"]["tb"]
        assert m["range"]["end"]["ticks"] >= m["range"]["start"]["ticks"]
        assert m["day"] is None or m["day"] >= 1
    sample = next(iter(d["media"].values()))["sample_id"]
    frame = client.get(f"/api/media/{project.id}/frame/{sample}")
    assert frame.status_code == 200
    target = d["target"]["frames"]
    assert d["tolerance"] == {"frames": target * 5 // 100, "rate": d["target"]["rate"]}
    ref = _shots(d)[0]["ref"]
    from urllib.parse import quote

    alts = client.get(f"/api/edits/{eid}/shots/{quote(ref, safe='')}/alternatives").json()["items"]
    assert alts
    assert all(isinstance(a["sample_id"], int) for a in alts)
    assert all(a["file"] for a in alts)


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


def _within(m: dict[str, Any], pct: int) -> bool:
    return abs(m["total_frames"] - m["target_frames"]) <= m["target_frames"] * pct // 100


def test_make_it_shorter_reuses_the_analysis_with_no_ai_call(drafted: Any) -> None:
    """M4 acceptance 3 (ADR 0071): a new length is a new version within tolerance, timed
    from the storyboard: no vision call, no AI call at all."""
    from mosaic.editing.service import create_edit

    project, control, client, edit_id, eid = _fresh(drafted, 23, 60)
    calls = len(fake.CALLS)
    made = client.post(f"/api/edits/{eid}/duration", json={"duration_s": 30})
    assert made.status_code == 201, made.text
    v = made.json()
    assert v["reason"] == "Made it 30 s"
    assert v["creator"] == "user"
    assert v["request"]["duration_s"] == 30
    assert v["metrics"]["target_frames"] == 899  # 30 s at 30000/1001
    assert _within(v["metrics"], v["request"]["tolerance_pct"])
    assert len(fake.CALLS) == calls, "no AI call, vision or any other"
    # The draft reloads with the very candidates the version was timed with.
    d = client.get(f"/api/edits/{eid}/draft").json()
    assert d["timeline"] == v["timeline"]
    assert not any("no longer available" in n for n in d["metrics"]["solver"]["notes"])
    listed = client.get(f"/api/projects/{project.id}/edits").json()["items"]
    card = next(e for e in listed if e["edit_id"] == eid)
    assert card["request"]["duration_s"] == 30, "the edit's request is its current one"
    assert card["name"].endswith("· 30 s"), "a default name follows the length"
    # `mosaic edit` with the old request makes a new edit; with the new one, finds this.
    old = EditRequest(duration_s=60, variant=23)
    assert create_edit(project, old, control, control.local_principal) != edit_id
    now = EditRequest(duration_s=30, variant=23)
    assert create_edit(project, now, control, control.local_principal) == edit_id
    assert client.post(f"/api/edits/{eid}/duration", json={"duration_s": 30}).status_code == 409
    assert client.post(f"/api/edits/{eid}/duration", json={"duration_s": 1}).status_code == 422
    # As a draft op it is undoable like any other.
    d = client.post(
        f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "set_duration", "duration_s": 45}}
    ).json()
    assert d["target"]["frames"] == 1349
    back = client.post(f"/api/edits/{eid}/draft/undo").json()
    assert back["target"]["frames"] == 899


def test_make_it_90_seconds(drafted: Any) -> None:
    """Acceptance 3 as written: longer, from the storyboard and its alternatives, with
    no AI call, within tolerance (ADR 0071)."""
    _, _, client, _, eid = _fresh(drafted, 25, 60)
    calls = len(fake.CALLS)
    v = client.post(f"/api/edits/{eid}/duration", json={"duration_s": 90}).json()
    assert v["reason"] == "Made it 90 s"
    assert v["metrics"]["target_frames"] == 2697
    assert len(fake.CALLS) == calls, "no AI call"
    m = v["metrics"]
    assert _within(m, v["request"]["tolerance_pct"])
    assert not m["solver"]["underfilled"]


def test_a_length_the_footage_cannot_fill_is_reported_not_sent_to_the_ai(drafted: Any) -> None:
    _, _, client, _, eid = _fresh(drafted, 27, 30)
    calls = len(fake.CALLS)
    m = client.post(f"/api/edits/{eid}/duration", json={"duration_s": 3600}).json()["metrics"]
    assert len(fake.CALLS) == calls
    assert m["solver"]["underfilled"]
    assert any("not enough usable footage" in n for n in m["solver"]["notes"])


def test_the_same_length_saves_one_version_at_most(drafted: Any) -> None:
    _, _, client, _, eid = _fresh(drafted, 26)
    count = len(client.get(f"/api/edits/{eid}/versions").json()["items"])
    # A pending change back to the base length: one version, not a detour.
    client.post(
        f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "set_duration", "duration_s": 45}}
    )
    back = client.post(f"/api/edits/{eid}/duration", json={"duration_s": 30})
    assert back.status_code == 201
    assert back.json()["request"]["duration_s"] == 30
    count += 1
    ref = _shots(client.get(f"/api/edits/{eid}/draft").json())[0]["ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}})
    assert client.post(f"/api/edits/{eid}/duration", json={"duration_s": 30}).status_code == 409
    assert len(client.get(f"/api/edits/{eid}/versions").json()["items"]) == count, "nothing saved"
    client.post(
        f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "set_duration", "duration_s": 40}}
    )
    made = client.post(f"/api/edits/{eid}/duration", json={"duration_s": 40})
    assert made.status_code == 201
    assert made.json()["reason"] == "Made it 40 s"
    assert len(client.get(f"/api/edits/{eid}/versions").json()["items"]) == count + 1


def test_a_beat_faster_and_a_shots_alternatives(drafted: Any) -> None:
    _, _, client, _, eid = _fresh(drafted, 24)
    d = client.get(f"/api/edits/{eid}/draft").json()
    beat = d["board"]["beats"][0]
    faster = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "pace_beat", "beat_id": beat["beat_id"]}},
    ).json()
    after = next(b for b in faster["board"]["beats"] if b["beat_id"] == beat["beat_id"])
    assert [s["length"] for s in after["shots"]] != [s["length"] for s in beat["shots"]]

    def mean_frames(state: dict[str, Any]) -> float:
        frames = [
            e["timeline_out"]["frames"] - e["timeline_in"]["frames"]
            for e in state["timeline"]["tracks"][0]["events"]
            if e["beat_id"] == beat["beat_id"]
        ]
        return sum(frames) / len(frames)

    assert mean_frames(faster) < mean_frames(d), "its shots are shorter on the timeline"
    ref = beat["shots"][0]["ref"]
    from urllib.parse import quote

    # A ref holds "#": percent-encoded in the path.
    got = client.get(f"/api/edits/{eid}/shots/{quote(ref, safe='')}/alternatives").json()
    alts = got["items"]
    assert got["locked"] is False
    used = {s["segment_id"] for s in _shots(d)}
    assert alts, "the beat's pool offers something"
    assert all(a["segment_id"] not in used for a in alts)
    named = [a["segment_id"] for a in beat["shots"][0]["alternatives"]]
    offered = [a["segment_id"] for a in alts]
    assert offered[: len([n for n in named if n in offered])] == [n for n in named if n in offered]
    swapped = client.post(
        f"/api/edits/{eid}/draft/ops",
        json={"op": {"kind": "replace_shot", "ref": ref, "segment_id": offered[0]}},
    )
    assert swapped.status_code == 200, swapped.text
    assert client.get(f"/api/edits/{eid}/shots/nope/alternatives").status_code == 404


def test_edit_categories_come_most_frequent_first(drafted: Any) -> None:
    project, _, client, _ = drafted
    items = client.get(f"/api/projects/{project.id}/edit-categories").json()["items"]
    assert len(items) == 22
    clips = [i["clips"] for i in items]
    assert clips == sorted(clips, reverse=True)
    assert clips[0] > 0, "the corpus has categorised clips"


def test_a_locked_shot_is_never_avoided_by_a_content_weight(drafted: Any) -> None:
    """Invariant 10: the owner tags a locked clip with a category the edit avoids; the
    lock wins and the shot stays (ADR 0072)."""
    from sqlalchemy import select

    from mosaic.storage.models_project import ClipTag, EditVersion

    project, _, client, edit_id, eid = _fresh(drafted, 28)
    d = client.get(f"/api/edits/{eid}/draft").json()
    e = d["timeline"]["tracks"][0]["events"][0]
    ref = e["origin"]["selection_ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}})
    client.post(f"/api/edits/{eid}/versions")
    asset = int(e["asset_id"][4:])
    with project.write() as s:
        s.add(ClipTag(asset_id=asset, tag="timelapse"))
        v = s.scalars(
            select(EditVersion)
            .where(EditVersion.edit_id == edit_id)
            .order_by(EditVersion.version.desc())
        ).first()
        assert v is not None
        v.request = {**v.request, "weights": {"timelapse": "avoid"}}
    after = client.get(f"/api/edits/{eid}/draft").json()
    refs = {x["origin"]["selection_ref"] for x in after["timeline"]["tracks"][0]["events"]}
    assert ref in refs
    assert not any("no longer available" in n for n in after["metrics"]["solver"]["notes"])
    assert "avoided" in after["metrics"]["retrieval"], "the avoid weight was applied"


def test_more_of_a_category_regenerates_with_the_new_weight(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRODUCT.md §8 (ADR 0074): one step more or less of a category, the whole edit
    regenerated with it (the prompts see it) and the owner's locks kept; refused at
    either end of the scale."""
    from mosaic.ai import client as ai_client
    from tests.support.runner import run_job

    project, control, client, _, eid = _fresh(drafted, 29, 47)
    seen: list[str] = []
    real = ai_client.AIClient.structured

    def spying(
        self: Any, capability: str, name: str, version: int, ctx: Any, *a: Any, **k: Any
    ) -> Any:
        if name == "planner":
            seen.append(ctx["preferences"])
        return real(self, capability, name, version, ctx, *a, **k)

    monkeypatch.setattr(ai_client.AIClient, "structured", spying)
    ref = _shots(client.get(f"/api/edits/{eid}/draft").json())[0]["ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": ref}})

    def step(more: bool) -> dict[str, Any]:
        r = client.post(
            f"/api/edits/{eid}/category", json={"category": "conversations", "more": more}
        )
        assert r.status_code == 202, r.text
        assert run_job(control, r.json()["job_id"]) == "done"
        v = client.get(f"/api/edits/{eid}").json()
        assert v["metrics"]["regenerated"]["scope"] == "all"
        assert any(s["ref"] == ref and s["locked"] for b in v["beats"] for s in b["shots"])
        return {"weight": r.json()["weight"], "version": v}

    up = step(True)
    assert up["weight"] == "more"
    assert up["version"]["request"]["weights"]["conversations"] == "more"
    assert "More of: conversations." in seen[-1], "the regeneration saw the new weight"
    assert step(True)["weight"] == "strong"
    top = client.post(
        f"/api/edits/{eid}/category", json={"category": "conversations", "more": True}
    )
    assert top.status_code == 409
    for want in ("more", "neutral", "less", "avoid"):
        got = step(False)
        assert got["weight"] == want
        weights = got["version"]["request"]["weights"]
        if want == "neutral":
            assert "conversations" not in weights, "neutral is no weight"
        else:
            assert weights["conversations"] == want
    assert "Avoid: conversations." in seen[-1]
    bottom = client.post(
        f"/api/edits/{eid}/category", json={"category": "conversations", "more": False}
    )
    assert bottom.status_code == 409
    card = next(
        e
        for e in client.get(f"/api/projects/{project.id}/edits").json()["items"]
        if e["edit_id"] == eid
    )
    assert card["request"]["weights"]["conversations"] == "avoid"
    assert (
        client.post(f"/api/edits/{eid}/category", json={"category": "x", "more": True}).status_code
        == 422
    )


def test_a_stronger_opening_and_a_different_ending(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.ai import client as ai_client
    from tests.support.runner import run_job

    _, control, client, _, eid = _fresh(drafted, 30, 49)
    directives: list[str] = []
    real = ai_client.AIClient.structured

    def spying(
        self: Any, capability: str, name: str, version: int, ctx: Any, *a: Any, **k: Any
    ) -> Any:
        if name == "reselect":
            directives.append(ctx["directive"])
            assert version == 2
        return real(self, capability, name, version, ctx, *a, **k)

    monkeypatch.setattr(ai_client.AIClient, "structured", spying)
    d = client.get(f"/api/edits/{eid}/draft").json()
    beats = [b["beat_id"] for b in d["board"]["beats"]]
    first = d["board"]["beats"][0]["shots"][0]["ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": first}})
    last_before = {s["segment_id"] for s in d["board"]["beats"][-1]["shots"] if not s["locked"]}
    for end, beat, reason in (
        ("opening", beats[0], "A stronger opening"),
        ("ending", beats[-1], "A different ending"),
    ):
        r = client.post(f"/api/edits/{eid}/regenerate", params={"scope": end})
        assert r.status_code == 202, r.text
        assert run_job(control, r.json()["job_id"]) == "done"
        v = client.get(f"/api/edits/{eid}").json()
        assert v["reason"] == reason
        assert v["metrics"]["regenerated"] == v["metrics"]["regenerated"] | {
            "beat_id": beat,
            "directive": end,
        }
    after = client.get(f"/api/edits/{eid}/draft").json()
    assert any(s["ref"] == first and s["locked"] for s in after["board"]["beats"][0]["shots"]), (
        "the opening keeps its lock"
    )
    last_after = {s["segment_id"] for s in after["board"]["beats"][-1]["shots"] if not s["locked"]}
    assert last_after
    assert last_after != last_before, "a different ending"
    assert directives[0].startswith("Make this the strongest possible opening")
    assert directives[1].startswith("Give the edit a different ending")


def test_one_clip_left_fails_with_a_reason_before_any_ai_call(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No plan can be made from one clip (two beats, no clip twice): generating and
    regenerating stop before any AI call, saying why (ADR 0074)."""
    import dataclasses

    from mosaic.editing import generate as gen
    from mosaic.editing import regenerate as regen
    from mosaic.editing.generate import TOO_FEW_CLIPS
    from mosaic.editing.service import create_edit, submit_generate
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from tests.support.runner import run_job

    project, control, client, _, eid = _fresh(drafted, 31, 51)
    calls = len(fake.CALLS)
    monkeypatch.setattr(regen, "scope_candidates", lambda scope, board, cands: cands[:1])
    job = client.post(f"/api/edits/{eid}/regenerate", params={"scope": "all"}).json()["job_id"]
    assert run_job(control, job) == "failed"
    assert [t.error for t in JobStore(control.db).tasks(job)] == [TOO_FEW_CLIPS]

    real = gen.edit_inputs

    def one_clip(*a: Any, **k: Any) -> Any:
        inp = real(*a, **k)
        return dataclasses.replace(inp, cands=inp.cands[:1])

    monkeypatch.setattr(gen, "edit_inputs", one_clip)
    edit_id = create_edit(
        project, EditRequest(duration_s=33, variant=31), control, control.local_principal
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job) == "failed"
    assert [t.error for t in JobStore(control.db).tasks(job)] == [TOO_FEW_CLIPS]
    assert len(fake.CALLS) == calls, "no AI call"


def test_a_weight_step_that_cannot_be_queued_is_put_back_and_keeps_the_owners_change(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant 10 (ADR 0074): the owner's op races in while the weight step is being
    queued; the step is put back by an op of its own, the owner's op stays applied."""
    from mosaic.editing import service
    from mosaic.editing.draft import DraftChangedError, LockShot

    project, _, client, edit_id, eid = _fresh(drafted, 32, 53)
    ref = _shots(client.get(f"/api/edits/{eid}/draft").json())[0]["ref"]

    def racing(*_: Any, **__: Any) -> int:
        service.change_draft(project, edit_id, "op", LockShot(ref=ref))
        raise DraftChangedError("the draft changed while it was being saved; try again")

    monkeypatch.setattr(service, "submit_regenerate", racing)
    r = client.post(f"/api/edits/{eid}/category", json={"category": "water", "more": True})
    assert r.status_code == 409
    d = client.get(f"/api/edits/{eid}/draft").json()
    assert next(s for s in _shots(d) if s["ref"] == ref)["locked"], "the owner's op stays"
    assert d["board"]["weight_changes"]["water"] == "neutral", "the weight is back"


def test_findings_apply_as_child_versions_or_are_ignored(
    drafted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S17 (ADR 0081): a finding's fix is applied as a child version and the finding is
    marked applied in it; one whose shot can't take the fix is skipped; one without a fix
    can only be ignored. Applying waits for unsaved storyboard changes."""
    from sqlalchemy import select

    from mosaic.core.clock import now_iso
    from mosaic.core.ids import new_ulid
    from mosaic.storage.models_project import Edit, EditFinding

    project, control, client, _ = drafted
    edit_id = generate(project, control, EditRequest(duration_s=30, variant=17))
    with project.db.session() as s:
        eid = s.scalar(select(Edit.uid).where(Edit.id == edit_id))
    start = client.get(f"/api/edits/{eid}/draft").json()
    version = start["base_version"]
    refs = [
        e["origin"]["selection_ref"]
        for e in start["timeline"]["tracks"][0]["events"]
        if e["kind"] != "title" and not e["origin"]["locked"]
    ]
    victim = refs[-1]
    with project.write() as s:
        s.query(EditFinding).filter(EditFinding.edit_id == edit_id).delete()
        for i, (code, ops) in enumerate(
            [
                ("repetition", [{"kind": "remove_shot", "ref": victim}]),
                (
                    "shaky_shot",
                    [{"kind": "replace_shot", "ref": refs[0], "segment_id": "seg_999999"}],
                ),
                ("beat_coverage", None),
            ]
        ):
            s.add(
                EditFinding(
                    uid=new_ulid(),
                    edit_id=edit_id,
                    version=version,
                    seq=i,
                    source="critic",
                    code=code,
                    severity="warning",
                    frame=0,
                    event_id=None,
                    text=code,
                    ops=ops,
                    status="open",
                    applied_in_version=None,
                    created_at=now_iso(),
                )
            )
    listed = client.get(f"/api/edits/{eid}/findings").json()
    assert listed["version"] == version
    items = listed["items"]
    assert [(f["code"], f["can_apply"], f["status"]) for f in items] == [
        ("repetition", True, "open"),
        ("shaky_shot", True, "open"),
        ("beat_coverage", False, "open"),
    ]
    rep, shaky, note = (f["finding_id"] for f in items)

    # Unsaved storyboard changes come first.
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": refs[0]}})
    held = client.post(f"/api/edits/{eid}/findings/{rep}/apply")
    assert held.status_code == 409
    assert "storyboard" in held.text
    client.post(f"/api/edits/{eid}/draft/undo")

    assert client.post(f"/api/edits/{eid}/findings/{shaky}/apply").status_code == 422

    # A failure while saving leaves the draft clean and the finding open (atomic).
    from mosaic.editing import draft as draft_mod

    real_commit = draft_mod.commit

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(draft_mod, "commit", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        client.post(f"/api/edits/{eid}/findings/{rep}/apply")
    monkeypatch.setattr(draft_mod, "commit", real_commit)
    assert not client.get(f"/api/edits/{eid}/draft").json()["dirty"]
    statuses = [f["status"] for f in client.get(f"/api/edits/{eid}/findings").json()["items"]]
    assert statuses == ["open", "open", "open"]
    from mosaic.storage.projects import Project as ProjectClass

    snapshots: list[int] = []
    real_checkpoint = ProjectClass.checkpoint

    def counted(self: Any, *args: Any, **kwargs: Any) -> Any:
        snapshots.append(1)
        return real_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(ProjectClass, "checkpoint", counted)
    applied = client.post(f"/api/edits/{eid}/findings/apply-all")
    monkeypatch.setattr(ProjectClass, "checkpoint", real_checkpoint)
    assert applied.status_code == 201, applied.text
    assert snapshots, "a snapshot follows the new version (ARCHITECTURE §4)"
    child = applied.json()
    assert child["version"] == version + 1
    assert child["skipped_findings"] == [shaky]
    events = child["timeline"]["tracks"][0]["events"]
    assert all(e["origin"].get("selection_ref") != victim for e in events)
    old = client.get(f"/api/edits/{eid}/findings", params={"version": version}).json()["items"]
    assert [(f["status"], f["applied_in_version"]) for f in old] == [
        ("applied", version + 1),
        ("open", None),
        ("open", None),
    ]
    again = client.post(f"/api/edits/{eid}/findings/{shaky}/apply")
    assert again.status_code == 409, "a finding on an older version"
    assert client.post(f"/api/edits/{eid}/findings/{note}/ignore").json() == {"ignored": 1}
    assert client.post(f"/api/edits/{eid}/findings/nope/ignore").status_code == 404
    new = client.get(f"/api/edits/{eid}/findings").json()
    assert new["version"] == version + 1, "the child version has its own findings"
    stored = client.get(f"/api/edits/{eid}").json()["findings"]
    assert [f["code"] for f in new["items"]] == [f["code"] for f in stored], "one row each"
    client.post(f"/api/edits/{eid}/findings/ignore-all")
    assert all(
        f["status"] == "ignored" for f in client.get(f"/api/edits/{eid}/findings").json()["items"]
    )
    assert client.post(f"/api/edits/{eid}/findings/apply-all").status_code == 422


def test_versions_compare_and_revert_over_the_api(drafted: Any) -> None:
    """S18 (ADR 0083): compare lists shot changes between two versions; revert makes a
    new version equal to an older one and never rewrites history."""
    from sqlalchemy import select

    from mosaic.storage.models_project import Edit

    project, control, client, _ = drafted
    edit_id = generate(project, control, EditRequest(duration_s=30, variant=29))
    with project.db.session() as s:
        eid = s.scalar(select(Edit.uid).where(Edit.id == edit_id))
    longer = client.post(f"/api/edits/{eid}/duration", json={"duration_s": 40})
    assert longer.status_code == 201, longer.text
    diff = client.get(f"/api/edits/{eid}/compare", params={"a": 1, "b": 2}).json()
    assert diff["a"] == 1
    assert diff["b"] == 2
    assert diff["changes"], "a longer cut changes shots"
    assert not diff["same"]
    assert {c["kind"] for c in diff["changes"]} <= {
        "replaced",
        "trimmed",
        "moved",
        "added",
        "removed",
    }
    for c in diff["changes"]:  # S18's words: file, length and beat on each side it is on
        for side in ("a", "b"):
            if c[f"event_{side}"]:
                assert c[f"file_{side}"]
                assert "/" not in c[f"file_{side}"]
                assert c[f"frames_{side}"] >= 1
                assert c[f"beat_{side}"]
            else:
                assert c[f"file_{side}"] is None
                assert c[f"frames_{side}"] is None
                assert c[f"beat_{side}"] is None
    first = _shots(client.get(f"/api/edits/{eid}/draft").json())[0]["ref"]
    client.post(f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": first}})
    assert client.get(f"/api/edits/{eid}/draft").json()["dirty"]
    back = client.post(f"/api/edits/{eid}/revert", json={"version": 1})
    assert back.status_code == 201, back.text
    v3 = back.json()
    assert v3["version"] == 3
    assert not client.get(f"/api/edits/{eid}/draft").json()["dirty"], "unsaved changes dropped"
    v1 = client.get(f"/api/edits/{eid}/versions/1").json()
    assert v3["timeline"] == v1["timeline"]
    assert client.get(f"/api/edits/{eid}/compare", params={"a": 1, "b": 3}).json()["same"]
    listed = client.get(f"/api/edits/{eid}/versions").json()["items"]
    assert [(v["version"], v["creator"], v["parent_version"]) for v in listed] == [
        (1, "ai", None),
        (2, "user", 1),
        (3, "user", 2),
    ]
    assert listed[2]["reason"] == "Reverted to v1"
    assert client.post(f"/api/edits/{eid}/revert", json={"version": 3}).status_code == 409
    assert client.post(f"/api/edits/{eid}/revert", json={"version": 9}).status_code == 404
    assert client.get(f"/api/edits/{eid}/compare", params={"a": 1, "b": 9}).status_code == 404


def test_s19_exports_a_prores_master_with_its_edl_over_the_api(drafted: Any) -> None:
    """S19 (ADR 0084): POST /renders with a preset, resolution and sidecars; the EDL is
    downloadable beside the video; system info lists each codec's encoders."""
    from mosaic.storage.models_project import Render
    from tests.support.runner import run_job

    project, control, client, eid = drafted
    codecs = client.get("/api/system/info").json()["codecs"]
    assert codecs["prores"], "FFmpeg's own ProRes encoder is always there"
    assert set(codecs) == {"h264", "hevc", "prores"}
    bad = client.post("/api/renders", json={"edit_id": eid, "final": True, "codec": "vp9"})
    assert bad.status_code == 422
    started = client.post(
        "/api/renders",
        json={
            "edit_id": eid,
            "final": True,
            "codec": "prores",
            "resolution": "720p",
            "sidecars": ["edl"],
        },
    )
    assert started.status_code == 202, started.text
    body = started.json()
    assert run_job(control, body["job_id"], timeout=900) == "done"
    with project.db.session() as s:
        r = s.get(Render, body["render_id"])
        assert r is not None
        assert (r.profile["codec"], r.profile["height"]) == ("prores", 720)
    base = f"/api/projects/{project.id}/renders/{body['render_id']}/file"
    video = client.get(base)
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/quicktime"
    edl = client.get(base, params={"part": "edl", "download": True})
    assert edl.status_code == 200
    assert edl.json()["version"] == body["version"]
    assert "attachment" in edl.headers["content-disposition"]
    assert client.get(base, params={"part": "srt"}).status_code == 404, "not asked for"

    # Re-render (S20) is the same export: codec, resolution, loudness and sidecars.
    tv = client.post(
        "/api/renders",
        json={
            "edit_id": eid,
            "final": True,
            "codec": "prores",
            "resolution": "720p",
            "loudness": "tv",
            "sidecars": ["edl"],
        },
    ).json()
    assert run_job(control, tv["job_id"], timeout=900) == "done"
    again = client.post(f"/api/projects/{project.id}/renders/{tv['render_id']}/rerender")
    assert again.status_code == 202, again.text
    assert run_job(control, again.json()["job_id"], timeout=900) == "done"
    with project.db.session() as s:
        first, second = s.get(Render, tv["render_id"]), s.get(Render, again.json()["render_id"])
        assert first is not None
        assert second is not None
        keep = ("codec", "height", "resolution", "loudness", "sidecars")
        assert {k: second.profile.get(k) for k in keep} == {k: first.profile.get(k) for k in keep}
        assert first.profile["loudness"] == "tv"


def test_s14_probes_a_music_track_for_its_card(
    drafted: Any, ffmpeg_bin: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S14 step 5 (ADR 0086): a track's name, length, sample rate and waveform; a file
    that isn't one, or isn't there, is refused in plain words."""
    from mosaic.media.ffmpeg.command import FFmpegCommand, InputSpec, OutputSpec, media_path
    from mosaic.media.ffmpeg.run import run

    _, _, client, _ = drafted
    track = tmp_path / "Horizon.wav"
    run(
        ffmpeg_bin,
        FFmpegCommand(
            inputs=[
                InputSpec("sine=frequency=440:sample_rate=44100:duration=3", [("-f", "lavfi")])
            ],
            outputs=[OutputSpec(media_path(track), [("-af", "afade=t=in:d=3")])],
            description="a fading-in track",
        ),
    )
    card = client.post("/api/music/probe", json={"path": str(track)})
    assert card.status_code == 200, card.text
    body = card.json()
    assert (body["name"], body["sample_rate"]) == ("Horizon.wav", 44100)
    assert abs(body["duration_ms"] - 3000) < 50
    assert len(body["peaks"]) == 48
    assert body["peaks"][0] < body["peaks"][-1] == 100, "a fade in rises"
    (tmp_path / "notes.mp3").write_text("not audio")
    assert (
        client.post("/api/music/probe", json={"path": str(tmp_path / "notes.mp3")}).status_code
        == 422
    )
    assert (
        client.post("/api/music/probe", json={"path": str(tmp_path / "gone.mp3")}).status_code
        == 422
    )
    assert client.post("/api/music/probe", json={"path": "Horizon.wav"}).status_code == 422

    # A track whose header reads but whose sound fails, or takes too long, to decode is
    # refused in plain words, never a server error (invariant 14).
    import subprocess

    from mosaic.media.ffmpeg import run as run_mod
    from mosaic.media.ffmpeg.run import FFmpegError

    real = run_mod.run
    for failure in (
        FFmpegError("decode failed", ["ffmpeg"], 1, "Invalid data"),
        subprocess.TimeoutExpired("ffmpeg", 60),
    ):

        def broken(binaries: Any, cmd: Any, *a: Any, _f: Exception = failure, **k: Any) -> Any:
            if getattr(cmd, "description", "").startswith("pcm "):
                raise _f
            return real(binaries, cmd, *a, **k)

        monkeypatch.setattr(run_mod, "run", broken)
        refused = client.post("/api/music/probe", json={"path": str(track)})
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == "Horizon.wav: it can't be read as audio"
    monkeypatch.setattr(run_mod, "run", real)


def test_regenerate_with_fixes_applies_them_then_regenerates_the_beats_left(
    drafted: Any,
) -> None:
    """S17 "Regenerate with fixes" (ADR 0089): the open findings with a fix are applied as
    a child version, then the beats holding an issue with no fix are regenerated in one
    job, one after the other in story order; a suggestion (info) regenerates nothing, and
    a beat with every shot locked is left alone. Unsaved changes come first; with nothing
    to do it is refused. The child version lists the findings applied in it."""
    from sqlalchemy import select

    from mosaic.core.clock import now_iso
    from mosaic.core.ids import new_ulid
    from mosaic.storage.models_project import Edit, EditFinding
    from tests.support.runner import run_job

    project, control, client, _ = drafted
    edit_id = generate(project, control, EditRequest(duration_s=90, variant=23))
    with project.db.session() as s:
        eid = s.scalar(select(Edit.uid).where(Edit.id == edit_id))
    start = client.get(f"/api/edits/{eid}/draft").json()
    shots = [e for e in start["timeline"]["tracks"][0]["events"] if e["kind"] != "title"]
    beats = [b["beat_id"] for b in start["board"]["beats"]]
    assert len(beats) == 3, beats
    first_of = {b: next(e for e in shots if e["beat_id"] == b) for b in beats}
    # Every shot of the first beat locked (saved as a version): an issue there is left alone.
    locked_beat = start["board"]["beats"][0]
    for sh in locked_beat["shots"]:
        if not sh["absorbed_by"]:
            client.post(
                f"/api/edits/{eid}/draft/ops",
                json={"op": {"kind": "lock_shot", "ref": sh["ref"]}},
            )
    assert client.post(f"/api/edits/{eid}/versions").status_code == 201
    v0 = client.get(f"/api/edits/{eid}").json()
    version = v0["version"]
    events = {e["event_id"]: e for e in v0["timeline"]["tracks"][0]["events"]}
    by_beat = {b: next(e for e in events.values() if e.get("beat_id") == b) for b in beats}
    victim = next(
        e["origin"]["selection_ref"]
        for e in reversed(list(events.values()))
        if e.get("beat_id") == beats[1] and not e["origin"]["locked"]
    )
    alternative = client.get(
        f"/api/edits/{eid}/shots/{quote(by_beat[beats[2]]['origin']['selection_ref'], safe='')}"
        "/alternatives"
    ).json()["items"][0]
    findings_ = [
        ("repetition", "warning", None, [{"kind": "remove_shot", "ref": victim}]),
        (
            "shaky_shot",
            "info",
            None,
            [
                {
                    "kind": "replace_shot",
                    "ref": by_beat[beats[2]]["origin"]["selection_ref"],
                    "segment_id": alternative["segment_id"],
                }
            ],
        ),
        ("ai_note", "warning", by_beat[beats[2]]["event_id"], None),  # issues, no fix
        ("ai_note", "blocking", by_beat[beats[1]]["event_id"], None),
        ("ai_note", "warning", by_beat[locked_beat["beat_id"]]["event_id"], None),  # locked
        ("ai_note", "info", first_of[beats[1]]["event_id"], None),  # a suggestion
    ]
    with project.write() as s:
        s.query(EditFinding).filter(EditFinding.edit_id == edit_id).delete()
        for i, (code, severity, event, ops) in enumerate(findings_):
            s.add(
                EditFinding(
                    uid=new_ulid(),
                    edit_id=edit_id,
                    version=version,
                    seq=i,
                    source="ai" if code == "ai_note" else "critic",
                    code=code,
                    severity=severity,
                    frame=0,
                    event_id=event,
                    text=code,
                    ops=ops,
                    status="open",
                    applied_in_version=None,
                    created_at=now_iso(),
                )
            )
    listed = client.get(f"/api/edits/{eid}/findings").json()["items"]
    assert [f["fix"] for f in listed] == [
        "Remove it",
        f"Replace it with {alternative['file']}",
        None,
        None,
        None,
        None,
    ]

    changed = client.post(
        f"/api/edits/{eid}/draft/ops", json={"op": {"kind": "lock_shot", "ref": victim}}
    )
    assert changed.json()["dirty"]
    assert client.post(f"/api/edits/{eid}/findings/regenerate").status_code == 409
    client.post(f"/api/edits/{eid}/draft/undo")

    started = client.post(f"/api/edits/{eid}/findings/regenerate")
    assert started.status_code == 202, started.text
    got = started.json()
    assert got["version"] == version + 1
    assert got["beats"] == [beats[1], beats[2]], "story order; the locked beat left alone"
    child = client.get(f"/api/edits/{eid}/findings", params={"version": version + 1}).json()
    assert [f["code"] for f in child["applied"]] == ["repetition", "shaky_shot"]
    assert all(f["applied_in_version"] == version + 1 for f in child["applied"])
    assert client.get(f"/api/edits/{eid}/draft").json()["regenerating"] == sorted(got["beats"])
    assert run_job(control, got["job_id"]) == "done"
    v = client.get(f"/api/edits/{eid}").json()
    assert v["version"] == version + 3, "one version per beat"
    assert v["parent_version"] == version + 2
    assert v["metrics"]["regenerated"]["beat_id"] == beats[2]
    mid = client.get(f"/api/edits/{eid}/versions/{version + 2}").json()
    assert mid["parent_version"] == version + 1, "regenerated on top of the fixes"
    assert mid["metrics"]["regenerated"]["beat_id"] == beats[1]
    after = client.get(f"/api/edits/{eid}/draft").json()
    kept = next(b for b in after["board"]["beats"] if b["beat_id"] == locked_beat["beat_id"])
    assert [s["segment_id"] for s in kept["shots"]] == [
        s["segment_id"] for s in locked_beat["shots"]
    ]

    # Nothing to fix: refused, with no job.
    client.post(f"/api/edits/{eid}/findings/ignore-all")
    nothing = client.post(f"/api/edits/{eid}/findings/regenerate")
    assert nothing.status_code == 422


def test_export_options_and_the_save_to_folder(
    drafted: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S19 (ADR 0091): each preset's size at each resolution and whether it can be encoded
    here, the version's defaults; "Save to" takes an existing folder this app can write
    to, on the desktop only."""
    _, _, client, eid = drafted
    got = client.get(f"/api/edits/{eid}/export").json()
    assert set(got["presets"]) == {"h264", "hevc", "prores"}
    for codec, p in got["presets"].items():
        assert set(p["bytes"]) == {"720p", "1080p", "1440p", "4k"}
        sizes = [p["bytes"][r] for r in ("720p", "1080p", "1440p", "4k")]
        assert sizes == sorted(sizes), codec
        assert sizes[0] > 0
        assert isinstance(p["available"], bool)
        assert (p["reason"] is None) == p["available"]
    h264, hevc, prores = (got["presets"][c]["bytes"]["1080p"] for c in ("h264", "hevc", "prores"))
    assert hevc < h264 < prores
    assert got["resolution"] in {"720p", "1080p", "1440p", "4k"}
    assert got["save_to"]["can_choose"] is True
    assert client.get(f"/api/edits/{eid}/export", params={"version": 99}).status_code == 404

    def render(save_to: str) -> Any:
        return client.post(
            "/api/renders",
            json={"edit_id": eid, "final": True, "codec": "h264", "save_to": save_to},
        )

    assert render(str(tmp_path / "nope")).status_code == 422
    assert render("relative/folder").status_code == 422
    project = drafted[0]
    among = project.root / "exports-here"
    among.mkdir(exist_ok=True)
    try:
        inside = render(str(among))
        assert inside.status_code == 422, "never among the footage"
        assert "outside your footage" in inside.text
    finally:
        among.rmdir()
    monkeypatch.setattr("mosaic.storage.placement.is_writable", lambda p: False)
    refused = render(str(tmp_path))
    assert refused.status_code == 422
    assert "can't be written" in refused.text
    monkeypatch.undo()
    monkeypatch.setattr("mosaic.core.runtime.server_mode", lambda: True)
    assert render(str(tmp_path)).status_code == 422
