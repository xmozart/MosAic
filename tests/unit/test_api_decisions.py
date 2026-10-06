"""PATCH /clips/{aid}/decision, POST /decisions/bulk and clip.updated (ADR 0042)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from tests.unit.test_decisions import _project


def _client(tmp_path: Path) -> tuple[Any, Any, dict[str, Any]]:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, ids = _project(tmp_path)
    pid = project.id
    project.close()
    svc = Services.create(ids["control"])
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app), svc, {"pid": pid, **ids}


def test_patch_bulk_and_validation(tmp_path: Path) -> None:
    client, _svc, ids = _client(tmp_path)
    base = f"/api/projects/{ids['pid']}"
    r = client.patch(f"{base}/clips/{ids['a']}/decision", json={"stars": 5, "tags": [" toucan "]})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "asset_id": ids["a"],
        "changed": ["stars", "tags"],
        "disposition": None,
        "stars": 5,
        "include": None,
        "note": None,
        "live_motion": None,
        "tags": ["toucan"],
    }
    r = client.patch(f"{base}/clips/{ids['a']}/decision", json={"stars": None})
    assert r.json()["stars"] is None, "null resets"
    assert r.json()["tags"] == ["toucan"], "left out: unchanged"
    for bad in ({"stars": 6}, {"disposition": "YES"}, {"include": "sometimes"}, {"x": 1}):
        assert client.patch(f"{base}/clips/{ids['a']}/decision", json=bad).status_code == 422
    assert client.patch(f"{base}/clips/999/decision", json={"stars": 1}).status_code == 404
    bulk = client.post(
        f"{base}/decisions/bulk",
        json={"asset_ids": [ids["a"], ids["b"], ids["a"]], "disposition": "REJECT"},
    )
    assert bulk.json() == {"updated": 2}
    lib = client.get(f"{base}/library").json()
    assert lib["items"] == [], "both rejected by the owner: hidden"
    assert lib["rejected_hidden"] == 3
    shown = client.get(f"{base}/library", params={"show_rejected": True}).json()["items"]
    assert {i["asset_id"]: i["decided_by"] for i in shown}[ids["a"]] == "user"


def test_decisions_are_streamed_as_clip_updated(tmp_path: Path) -> None:
    from mosaic.jobs.model import JobSpec, TaskSpec

    client, svc, ids = _client(tmp_path)
    pid = ids["pid"]
    svc.executor.submit(svc.principal, JobSpec(pid, "analysis", tasks=[TaskSpec("x", "s")]))

    def act() -> None:
        time.sleep(0.8)  # the stream is subscribed
        client.patch(f"/api/projects/{pid}/clips/{ids['b']}/decision", json={"include": "always"})
        time.sleep(0.8)
        t = svc.store.lease("w", "cpu")
        assert t is not None
        svc.store.complete(t.id, "w")

    errors: list[BaseException] = []

    def guarded() -> None:
        try:
            act()
        except BaseException as exc:  # surfaced below, not lost in the thread
            errors.append(exc)

    worker = threading.Thread(target=guarded)
    worker.start()
    with client.stream("GET", "/api/events", params={"project": pid, "until_idle": True}) as r:
        text = "".join(r.iter_text())
    worker.join()
    assert not errors, errors
    assert "event: clip.updated" in text
    assert f'"asset_id": {ids["b"]}' in text
    assert '"fields": ["include"]' in text
    assert not svc.events._queues, "the stream unsubscribed when it ended"


def test_a_large_bulk_change_sends_one_refetch_event(tmp_path: Path, monkeypatch: Any) -> None:
    from mosaic.app.routers import library

    client, svc, ids = _client(tmp_path)
    monkeypatch.setattr(library, "BULK_EVENTS", 1)
    hub = svc.events.subscribe()
    client.post(
        f"/api/projects/{ids['pid']}/decisions/bulk",
        json={"asset_ids": [ids["a"], ids["b"]], "stars": 2},
    )
    assert list(hub) == [
        ("clip.updated", {"project_id": ids["pid"], "asset_id": None, "fields": ["stars"]})
    ]
    svc.events.unsubscribe(hub)


def test_a_stream_that_falls_behind_gets_one_refetch_marker() -> None:
    from mosaic.app.services import EventHub

    hub = EventHub()
    q = hub.subscribe()
    for i in range(EventHub.MAX + 5):
        hub.publish("clip.updated", {"project_id": "P", "asset_id": i, "fields": ["stars"]})
    assert q[0] == ("clip.updated", {"project_id": "P", "asset_id": None, "fields": []})
    assert len(q) < EventHub.MAX
