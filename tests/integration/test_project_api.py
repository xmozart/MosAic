"""Recents, folder preview, creation with a scan-only job, and inventory (M2 step 5a;
S3–S5; ADR 0038)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _client(
    control: Any, monkeypatch: pytest.MonkeyPatch | None = None, mode: str = "desktop"
) -> Any:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    if monkeypatch is not None:
        monkeypatch.setenv("MOSAIC_MODE", mode)
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app, base_url="https://testserver")


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for here, _dirs, files in os.walk(folder):
        for f in files:
            p = Path(here) / f
            st = p.stat()
            out[str(p.relative_to(folder))] = (st.st_size, st.st_mtime_ns)
    return out


def test_preview_writes_nothing_then_create_scans_only(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.jobs.store import JobStore
    from mosaic.storage.control import ControlDB
    from tests.support.runner import run_job

    trip = tmp_path / "trip"
    shutil.copytree(corpus_dir, trip)
    control = ControlDB()
    client = _client(control)
    before = _snapshot(trip)
    pv = client.post("/api/projects/preview", json={"path": str(trip)})
    assert pv.status_code == 200, pv.text
    body = pv.json()
    assert body["fs_class"] == "local"
    assert body["placement"] == "in_folder"
    assert body["counts"]["videos"] > 5
    assert body["project_id"] is None
    assert _snapshot(trip) == before, "preview performs no writes (S4)"
    assert not (trip / ".mosaic-project.json").exists()

    created = client.post("/api/projects", json={"path": str(trip), "name": "Synthetic"})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert created.json()["created"] is True
    job = created.json()["scan_job"]
    assert run_job(control, job, timeout=600) == "done"
    kinds = {t.kind for t in JobStore(control.db).tasks(job)}
    assert kinds <= {"analysis.scan", "media.probe", "media.group"}, kinds

    again = client.post("/api/projects", json={"path": str(trip)})
    assert again.json()["created"] is False
    assert again.json()["id"] == pid

    listed = client.get("/api/projects").json()["items"]
    me = next(i for i in listed if i["id"] == pid)
    assert me["missing"] is False
    assert me["status"]["state"] in ("scanned", "scanning")
    assert me["card"]["clips"] > 5

    inv = client.get(f"/api/projects/{pid}/inventory").json()
    assert inv["summary"]["clips"] == me["card"]["clips"]
    assert inv["cameras"], "cameras found"
    unread = [a for a in inv["attention"] if a["kind"] == "unreadable"]
    assert unread, "the corrupt file is listed"
    assert all("ffprobe" not in (a["reason"] or "").lower() for a in unread), "catalog reasons only"
    assert inv["notes"]["chaptered_recordings"] >= 1, "GoPro chapters joined"
    files = f"/api/projects/{pid}/inventory/files"
    group = unread[0]
    listed_files = client.get(files, params={"kind": "unreadable", "group": group["group"]})
    assert listed_files.status_code == 200, listed_files.text
    paths = [f["path"] for f in listed_files.json()["items"]]
    assert len(paths) == group["count"]
    assert all(not p.startswith("/") for p in paths), "relative to the project folder"
    if group["count"] == 1:
        assert group["example"] == paths[0].rsplit("/", 1)[-1]
    assert client.get(files, params={"kind": "unreadable", "group": 999999}).status_code == 404
    assert client.get(files, params={"kind": "everything"}).status_code == 422
    assert client.get(files, params={"kind": "cloud"}).json()["items"] == []
    assert all("limited" in c for c in inv["cameras"])
    from collections import Counter

    from mosaic.storage.models_project import Asset
    from mosaic.storage.projects import open_project

    opened = open_project(control, control.local_principal, trip)
    with opened.db.session() as s:
        dated = Counter(
            a.capture_time[:10]
            for a in s.query(Asset).filter(Asset.kind == "video", Asset.status == "ok")
            if a.capture_time
        )
    opened.close()
    assert {d["date"]: d["clips"] for d in inv["days"] if d["clips"]} == dict(dated)
    assert all(d["n"] >= 1 for d in inv["days"]), "days are numbered from the first video"


def test_list_opens_no_project_db_and_flags_missing_folders(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.storage import db as db_module
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project

    control = ControlDB()
    gone = tmp_path / "gone"
    gone.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", gone / "speech.mp4")
    init_project(control, control.local_principal, gone).close()
    client = _client(control)
    shutil.rmtree(gone)
    opened: list[Path] = []
    real = db_module.Database.__init__

    def spy(self: Any, path: Path, tree: str, **kw: Any) -> None:
        if tree == "project":
            opened.append(path)
        real(self, path, tree, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(db_module.Database, "__init__", spy)
    items = client.get("/api/projects").json()["items"]
    assert opened == [], "recents render from the control DB only (S3)"
    assert [i["missing"] for i in items] == [True]


def test_analyzed_card_has_cover_frames(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    item = next(i for i in client.get("/api/projects").json()["items"] if i["id"] == project.id)
    assert item["status"]["state"] == "analyzed"
    assert item["card"]["analyzed"] is True
    cover = item["card"]["cover"]
    assert len(cover) == 3
    for sid in cover:
        assert client.get(f"/api/media/{project.id}/frame/{sid}").status_code == 200


def test_server_mode_uses_media_roots(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.storage.control import ControlDB

    media = tmp_path / "media"
    shutil.copytree(corpus_dir, media / "Trip")
    (tmp_path / "elsewhere").mkdir()
    control = ControlDB()
    client = _client(control, monkeypatch, "server")
    csrf = client.post("/api/auth/setup", json={"password": "correct horse battery"}).json()["csrf"]
    h = {"X-CSRF-Token": csrf}
    rid = client.post("/api/admin/media-roots", json={"path": str(media)}, headers=h).json()["id"]
    pv = client.post("/api/projects/preview", json={"root": rid, "path": "Trip"}, headers=h)
    assert pv.status_code == 200, pv.text
    assert (
        client.post(
            "/api/projects/preview", json={"path": str(tmp_path / "elsewhere")}, headers=h
        ).status_code
        == 422
    )
    out = client.post(
        "/api/projects/preview", json={"root": rid, "path": "../elsewhere"}, headers=h
    )
    assert out.status_code == 403
    made = client.post("/api/projects", json={"root": rid, "path": "Trip"}, headers=h)
    assert made.status_code == 201, made.text
    listed = client.get("/api/projects").json()["items"]
    assert listed[0]["folder"] == {"root": rid, "path": "Trip"}
    assert str(media) not in str(listed)


def test_cloud_download_reads_then_rescans(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import update

    from mosaic.jobs.store import JobStore
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_project import MediaFile
    from mosaic.storage.projects import init_project
    from tests.support.runner import run_job

    trip = tmp_path / "trip"
    trip.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", trip / "speech.mp4")
    control = ControlDB()
    client = _client(control)
    pid = client.post("/api/projects", json={"path": str(trip)}).json()["id"]
    first = JobStore(control.db).jobs(pid, None, kind="scan", limit=1)[0].id
    assert run_job(control, first, timeout=300) == "done"
    project = init_project(control, control.local_principal, trip)
    with project.write() as s:  # as a scan of an iCloud placeholder would record it
        s.execute(update(MediaFile).values(status="offline"))
    project.close()
    clip = trip / "speech.mp4"
    before = (clip.stat().st_size, clip.stat().st_mtime_ns)
    job = client.post(f"/api/projects/{pid}/cloud-files/download").json()["job_id"]
    assert run_job(control, job, timeout=300) == "done"
    tasks = JobStore(control.db).tasks(job)
    assert [t.kind for t in tasks][:2] == ["media.cloud_download", "analysis.scan"]
    assert next(t for t in tasks if t.kind == "media.cloud_download").result["downloaded"] == 1
    assert (clip.stat().st_size, clip.stat().st_mtime_ns) == before, "the original is only read"


def test_a_hung_folder_check_does_not_hold_the_list(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from mosaic.app.routers import project_list
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project

    trip = tmp_path / "share"
    trip.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", trip / "speech.mp4")
    control = ControlDB()
    init_project(control, control.local_principal, trip).close()
    client = _client(control)

    def hung(_path: str) -> bool:
        time.sleep(2)  # an offline network share
        return True

    monkeypatch.setattr(project_list, "_exists", hung)
    started = time.monotonic()
    items = client.get("/api/projects").json()["items"]
    assert time.monotonic() - started < 1.0
    assert items[0]["missing"] is None, "still checking"


def test_external_projects_are_recognised_and_placement_refusals_are_422(
    corpus_dir: Path, tmp_path: Path
) -> None:
    from mosaic.storage.control import ControlDB

    ro = tmp_path / "readonly"
    ro.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", ro / "speech.mp4")
    ro.chmod(0o555)
    try:
        control = ControlDB()
        client = _client(control)
        refused = client.post("/api/projects", json={"path": str(ro), "placement": "in_folder"})
        assert refused.status_code == 422, refused.text
        assert not (ro / ".mosaic-project.json").exists()
        made = client.post("/api/projects", json={"path": str(ro)})
        assert made.status_code == 201, made.text
        assert made.json()["placement"] == "external"
        pid = made.json()["id"]
        pv = client.post("/api/projects/preview", json={"path": str(ro)}).json()
        assert pv["project_id"] == pid, "an external project is found without a descriptor"
        again = client.post("/api/projects", json={"path": str(ro), "placement": "split"})
        assert again.json() == {
            **again.json(),
            "id": pid,
            "created": False,
            "placement": "external",
        }
    finally:
        ro.chmod(0o755)


def test_remove_from_recents_keeps_every_file(corpus_dir: Path, tmp_path: Path) -> None:
    from mosaic.storage.control import ControlDB

    trip = tmp_path / "trip"
    trip.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", trip / "speech.mp4")
    control = ControlDB()
    client = _client(control)
    pid = client.post("/api/projects", json={"path": str(trip)}).json()["id"]
    before = _snapshot(trip)
    assert client.delete(f"/api/projects/{pid}/recent").status_code == 204
    assert [i["id"] for i in client.get("/api/projects").json()["items"]] == []
    lock = "MosAic/.lock"
    after = _snapshot(trip)
    assert lock not in after, "the lease is released like close does, not left to expire"
    assert after == {k: v for k, v in before.items() if k != lock}, "every other file untouched"
    again = client.post("/api/projects", json={"path": str(trip)}).json()
    assert again == {**again, "id": pid, "created": False}, "opening the folder brings it back"


def test_removing_an_external_project_with_edits_keeps_its_link(
    corpus_dir: Path, tmp_path: Path
) -> None:
    """External placement is known only through its registry row; an indexed edit points at
    that row. Removing from recents hides it, so neither is lost (ADR 0039)."""
    from mosaic.storage.control import ControlDB

    trip = tmp_path / "trip"
    trip.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", trip / "speech.mp4")
    control = ControlDB()
    client = _client(control)
    made = client.post("/api/projects", json={"path": str(trip), "placement": "external"}).json()
    pid = made["id"]
    assert made["placement"] == "external"
    control.index_edit(control.local_principal, "01EDIT0000000000000000000A", pid)
    assert (
        client.post(
            f"/api/projects/{pid}/open", json={"read_only": False, "take_over": False}
        ).status_code
        == 200
    )
    assert client.delete(f"/api/projects/{pid}/recent").status_code == 204
    assert client.get("/api/projects").json()["items"] == []
    assert control.project_for_edit("01EDIT0000000000000000000A") == pid
    assert pid not in _held(client)
    again = client.post("/api/projects", json={"path": str(trip)}).json()
    assert again == {**again, "id": pid, "created": False, "placement": "external"}
    assert [i["id"] for i in client.get("/api/projects").json()["items"]] == [pid]
    assert client.delete("/api/projects/01NOPE00000000000000000000/recent").status_code == 404


def _held(client: Any) -> set[str]:
    return set(client.app.state.services.leases.held)
