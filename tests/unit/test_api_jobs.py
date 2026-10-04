from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from mosaic.app.main import create_app
from mosaic.app.services import Services
from mosaic.jobs.model import JobSpec, TaskSpec


def _client() -> tuple[TestClient, Services]:
    svc = Services.create()
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver", "127.0.0.1"}
    return TestClient(app), svc


def _job(svc: Services, n: int = 2) -> int:
    return svc.executor.submit(
        svc.principal, JobSpec("P1", "analysis", tasks=[TaskSpec("x", "probe")] * n)
    )


def test_system_info() -> None:
    client, _ = _client()
    r = client.get("/api/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "desktop"
    assert "encoders" in body


def test_host_header_allowlist() -> None:
    client, _ = _client()
    r = client.get("/api/system/info", headers={"host": "evil.example.com"})
    assert r.status_code == 421
    prod = TestClient(create_app(Services.create()))
    assert prod.get("/api/system/info").status_code == 421  # "testserver" is not allowed
    assert prod.get("/api/system/info", headers={"host": "127.0.0.1:8765"}).status_code == 200


def test_jobs_pagination_detail_and_control() -> None:
    client, svc = _client()
    ids = [_job(svc) for _ in range(3)]
    page1 = client.get("/api/jobs", params={"limit": 2}).json()
    assert [j["job_id"] for j in page1["items"]] == [ids[2], ids[1]]
    page2 = client.get("/api/jobs", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
    assert [j["job_id"] for j in page2["items"]] == [ids[0]]
    assert page2["next_cursor"] is None
    detail = client.get(f"/api/jobs/{ids[0]}").json()
    assert detail["stages"] == {"probe": {"total": 2, "done": 0, "failed": 0}}
    assert detail["progress"]["total"] == 2
    assert client.post(f"/api/jobs/{ids[0]}/pause").json()["state"] == "paused"
    assert client.post(f"/api/jobs/{ids[0]}/resume").json()["state"] == "running"
    assert client.post(f"/api/jobs/{ids[0]}/cancel").json()["state"] == "cancelled"
    assert client.post(f"/api/jobs/{ids[0]}/explode").status_code == 404
    assert client.get("/api/jobs/9999").status_code == 404


def test_pagination_beyond_two_hundred() -> None:
    client, svc = _client()
    ids = [_job(svc, 1) for _ in range(205)]
    seen: list[int] = []
    cursor = None
    while True:
        params = {"limit": 50} if cursor is None else {"limit": 50, "cursor": cursor}
        body = client.get("/api/jobs", params=params).json()
        seen += [j["job_id"] for j in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(ids, reverse=True)


def test_retry_on_finished_job_does_not_reopen_it() -> None:
    client, svc = _client()
    job = _job(svc, 1)
    t = svc.store.lease("w", "cpu")
    assert t is not None
    svc.store.complete(t.id, "w")
    assert client.post(f"/api/jobs/{job}/retry-failed").json()["state"] == "done"
    assert client.post(f"/api/jobs/{job}/cancel").json()["state"] == "done"


def test_sse_streams_state_and_progress() -> None:
    client, svc = _client()
    job = _job(svc, 1)

    def finish() -> None:
        time.sleep(0.8)
        t = svc.store.lease("w", "cpu")
        assert t is not None
        svc.store.complete(t.id, "w")

    threading.Thread(target=finish).start()
    with client.stream("GET", "/api/events", params={"project": "P1", "until_idle": True}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    assert "event: job.state" in text
    assert "event: job.progress" in text
    assert '"state": "done"' in text
    assert f'"job_id": {job}' in text
