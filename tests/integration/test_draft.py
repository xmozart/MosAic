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
