"""M2 acceptance 1 and 3 (docs/milestones/M2.md), in process.

1. A server with one media root reaches a first rendered preview edit through the HTTP API
   alone, the calls the web UI makes: sign-in setup, media root, folder preview, create (scan),
   analysis, edit, preview render, ranged playback. No CLI and no direct service calls; jobs
   run on an in-process worker, as the container's worker runs them. `scripts/docker-e2e.sh`
   runs the same flow against `docker compose up` (ADR 0056).
3. An API key saved through the API never appears in an API response, the logs, the project
   folder, the databases or anything else under app data. Browser storage is covered by the
   frontend (`AppSettings.test.tsx`, `System.test.tsx`: the key is in neither storage).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.support.runner import run_job

pytestmark = [pytest.mark.acceptance, pytest.mark.models]

PASSWORD = "correct horse battery"
# Unmistakable, never a real key; the scan looks for all of it and for all but its last 4
# (the only part the UI may show).
CANARY = "sk-ant-api03-MOSAIC-CANARY-7f3c9e1d5b2a-NEVER-STORE-ME-QRST"
CLIPS = ("A001_basic.mp4", "A002_basic.mp4", "speech.mp4", "GX010042.MP4", "GX020042.MP4")


class Recorder:
    """Every request and response body the browser would see."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.seen: list[bytes] = []

    def __getattr__(self, verb: str) -> Any:
        call = getattr(self.client, verb)

        def wrapped(*a: Any, **kw: Any) -> Any:
            r = call(*a, **kw)
            self.seen.append(r.content + str(dict(r.headers)).encode())
            return r

        return wrapped


def _files_bytes(root: Path) -> list[tuple[Path, bytes]]:
    return [(p, p.read_bytes()) for p in root.rglob("*") if p.is_file()]


def test_browser_flow_reaches_a_rendered_preview_and_the_key_leaks_nowhere(
    corpus_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.core.paths import app_data_dir
    from mosaic.storage.control import ControlDB

    caplog.set_level(logging.DEBUG)
    media = tmp_path / "media"
    (media / "Trip").mkdir(parents=True)
    for name in CLIPS:
        shutil.copy2(corpus_dir / name, media / "Trip" / name)
    before = {p.name: p.stat().st_mtime_ns for p in (media / "Trip").iterdir()}
    master = tmp_path / "run-secrets" / "master_key"
    master.parent.mkdir()
    master.write_text("m" * 40)
    monkeypatch.setenv("MOSAIC_MODE", "server")
    monkeypatch.setenv("MOSAIC_FOLDER_DB", "never")
    monkeypatch.setenv("MOSAIC_MASTER_KEY_FILE", str(master))
    monkeypatch.setenv("MOSAIC_DOCKER_SECRETS_DIR", str(tmp_path / "run-secrets"))
    monkeypatch.delenv("MOSAIC_SECRET_AI_ANTHROPIC", raising=False)

    control = ControlDB()
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = Recorder(TestClient(app, base_url="https://testserver"))

    # S1/S2: first-run admin setup.
    assert client.get("/api/auth/status").json()["setup_required"] is True
    h = {"X-CSRF-Token": client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]}

    # S22: the key is entered once (write-only), checked, and shown as its last 4 only.
    put = client.put("/api/secrets/ai/anthropic", json={"value": CANARY}, headers=h)
    assert put.status_code in (200, 204), put.text
    assert "QRST" in str(client.get("/api/providers").json()), "last 4 are shown"
    check = client.post("/api/secrets/ai/anthropic/validate", headers=h)
    assert check.status_code < 500, "a check that can't reach the provider isn't a crash"
    # The analysis itself runs on the offline fake provider (no test reaches a real one).
    fake = client.patch(
        "/api/providers", json={"all": {"provider": "fake", "model": "fake"}}, headers=h
    )
    assert fake.status_code == 200, fake.text

    # S22 (admin): one media root.
    root = client.post("/api/admin/media-roots", json={"path": str(media)}, headers=h)
    assert root.status_code in (200, 201), root.text
    rid = root.json()["id"]
    assert [
        e["name"] for e in client.get("/api/fs/browse", params={"root": rid}).json()["items"]
    ] == ["Trip"]

    # S4: preview, then create: a scan-only job.
    pv = client.post("/api/projects/preview", json={"root": rid, "path": "Trip"}, headers=h)
    assert pv.status_code == 200, pv.text
    assert pv.json()["placement"] == "split", "MOSAIC_FOLDER_DB=never (ADR 0055)"
    made = client.post("/api/projects", json={"root": rid, "path": "Trip"}, headers=h)
    assert made.status_code == 201, made.text
    pid, scan = made.json()["id"], made.json()["scan_job"]
    assert run_job(control, scan, timeout=600) == "done"
    inv = client.get(f"/api/projects/{pid}/inventory").json()
    assert inv["summary"]["clips"] == len(CLIPS) - 1, "the chaptered recording is one clip"

    # S8/S9: analysis in quick mode.
    est = client.get(f"/api/projects/{pid}/analysis/estimate", params={"mode": "quick"})
    assert est.status_code == 200, est.text
    run = client.post(
        f"/api/projects/{pid}/analysis-runs", json={"mode": "quick", "cost_limit": 1.0}, headers=h
    )
    assert run.status_code in (200, 202), run.text
    assert run_job(control, run.json()["job_id"], timeout=1800) == "done"
    progress = client.get(f"/api/projects/{pid}/analysis/progress").json()
    assert progress["ready_to_browse"] is True
    lib = client.get(f"/api/projects/{pid}/library").json()
    assert lib["items"], "S10 shows the analysed clips"

    # S14: create an edit; it generates in a job.
    request = {"duration_s": 20, "story": "cinematic_journey", "aspect": "16:9"}
    e = client.post("/api/edits/estimate", json={"project_id": pid, "request": request}, headers=h)
    assert e.status_code == 200, e.text
    created = client.post(f"/api/projects/{pid}/edits", json={"request": request}, headers=h)
    assert created.status_code == 202, created.text
    eid = created.json()["edit_id"]
    assert run_job(control, created.json()["job_id"], timeout=900) == "done"
    edit = client.get(f"/api/edits/{eid}").json()
    assert edit["version"] >= 1

    # S17: a preview render, then playback with a Range request.
    r = client.post("/api/renders", json={"edit_id": eid, "final": False}, headers=h)
    assert r.status_code == 202, r.text
    rid_render = r.json()["render_id"]
    assert run_job(control, r.json()["job_id"], timeout=900) == "done"
    rows = client.get(f"/api/projects/{pid}/renders").json()["items"]
    assert next(x for x in rows if x["render_id"] == rid_render)["status"] == "done"
    part = client.get(
        f"/api/projects/{pid}/renders/{rid_render}/file", headers={"Range": "bytes=0-1023"}
    )
    assert part.status_code == 206
    assert len(part.content) == 1024
    report = client.get(f"/api/edits/{eid}/report")
    assert report.status_code == 200

    # Originals are untouched (invariant 1).
    assert {
        p.name: p.stat().st_mtime_ns
        for p in (media / "Trip").iterdir()
        if p.is_file() and p.name in before
    } == before

    # Acceptance 3: the key appears nowhere but the encrypted store.
    control.db.engine.dispose()
    needles = (CANARY.encode(), CANARY[:-4].encode())
    leaks: list[str] = []
    for i, body in enumerate(client.seen):
        if any(n in body for n in needles):
            leaks.append(f"API exchange #{i}")
    if any(n.decode() in caplog.text for n in needles):
        leaks.append("log records")
    for where in (app_data_dir(), media):
        for path, data in _files_bytes(where):
            if any(n in data for n in needles):
                leaks.append(str(path))
    assert not leaks, f"the API key leaked into: {leaks}"
    stored = [p for p in app_data_dir().rglob("*") if p.is_file() and "secret" in p.name.lower()]
    assert stored, "the key was saved somewhere (encrypted)"
