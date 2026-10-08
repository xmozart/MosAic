"""S21 storage and removal, S23 diagnostics (ADR 0051)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from mosaic.app.main import create_app
from mosaic.app.services import Services
from mosaic.core.paths import DESCRIPTOR_NAME, WORKSPACE_DIR, app_data_dir
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.storage import cleanup, provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import Task
from mosaic.storage.models_project import Artifact, Edit, EditVersion, Render
from mosaic.storage.projects import Project, init_project
from tests.support.runner import run_job

T = "2026-07-15T09:00:00+00:00"


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def setup(tmp_path: Path) -> tuple[ControlDB, Project, TestClient, Path]:
    folder = tmp_path / "Trip"
    folder.mkdir()
    original = folder / "IMG_0001.MOV"
    original.write_bytes(b"\x00original footage" * 1000)
    control = ControlDB()
    project = init_project(control, control.local_principal, folder, name="Costa Rica 2026")
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
    store = project.artifacts
    for kind, n, size in (
        ("proxy", 3, 5000),
        ("tickmap", 3, 100),
        ("mosaic", 4, 800),
        ("chunk", 5, 700),
        ("frame", 6, 300),
        ("probe", 2, 50),
    ):
        for i in range(n):
            store.put_bytes(kind, f"{kind}{i:04d}xx", b"x" * size, provenance_id=prov)
    with project.write() as s:
        e = Edit(uid="01JEDIT0000000000000000001", name="Cut", request={}, created_at=T)
        s.add(e)
        s.flush()
        s.add(
            EditVersion(
                edit_id=e.id,
                version=1,
                creator="ai",
                reason="generate",
                key="k",
                request={},
                rate="30/1",
                beats=[],
                timeline={"tracks": [{"events": []}], "duration": {"frames": 0, "rate": "30/1"}},
                metrics={},
                findings=[],
                provenance_id=prov,
                created_at=T,
            )
        )
        r = Render(
            edit_id=e.id,
            version=1,
            profile={"kind": "final", "width": 1920, "height": 1080, "lossless": False},
            status="done",
            metrics={},
            created_at=T,
            path="renders/edt_0001/v001-final-r0001.mp4",
        )
        s.add(r)
    out = project.workspace / "renders" / "edt_0001" / "v001-final-r0001.mp4"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"r" * 4000)
    svc = Services.create(control)
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    assert client.post(f"/api/projects/{project.id}/open").status_code == 200
    return control, project, client, original


def _counts(project: Project) -> dict[str, int]:
    """Rows per table (the artifact index left out): durable data."""
    with project.db.session() as s:
        names = inspect(s.get_bind()).get_table_names()
        return {
            n: s.execute(
                select(func.count()).select_from(__import__("sqlalchemy").table(n))
            ).scalar_one()
            for n in names
            if n != "artifact" and not n.startswith("sqlite") and "fts" not in n and "vec" not in n
        }


def test_storage_breakdown_and_clearing_keeps_durable_data(setup: Any) -> None:
    control, project, client, original = setup
    before = _digest(original)
    st = client.get(f"/api/projects/{project.id}/storage").json()
    groups = {g["id"]: g for g in st["groups"]}
    assert groups["previews"] == {
        "id": "previews",
        "label": "Previews",
        "bytes": 15300,
        "regenerable": True,
    }
    assert groups["render_cache"]["bytes"] == 3500
    assert groups["frames"]["bytes"] == 1800 + 3200  # frames and contact sheets: kept
    assert groups["frames"]["regenerable"] is False
    assert groups["renders"]["bytes"] == 4000
    assert groups["analysis"]["bytes"] >= 100  # the DB plus the probe artifacts
    assert st["regenerable_bytes"] == 15300 + 3500
    assert st["total_bytes"] == sum(g["bytes"] for g in st["groups"])
    durable = _counts(project)
    kept_files = [
        project.artifacts.path("frame", "frame0000xx"),
        project.artifacts.path("probe", "probe0000xx"),
    ]
    gone_files = [
        project.artifacts.path("proxy", "proxy0000xx"),
        project.artifacts.path("chunk", "chunk0000xx"),
    ]

    job = client.post(f"/api/projects/{project.id}/storage/clear-cache").json()["job_id"]
    assert run_job(control, job, timeout=120) == "done"
    after = client.get(f"/api/projects/{project.id}/storage").json()
    by = {g["id"]: g["bytes"] for g in after["groups"]}
    assert by["previews"] == by["render_cache"] == 0
    assert by["frames"] == 5000
    assert by["renders"] == 4000
    assert after["regenerable_bytes"] == 0
    assert all(not p.exists() for p in gone_files)
    assert all(p.exists() for p in kept_files)
    assert not project.artifacts.exists("proxy", "proxy0000xx")
    assert project.artifacts.exists("frame", "frame0000xx")
    assert _counts(project) == durable, "clearing never deletes durable data (S21)"
    with project.db.session() as s:
        kinds = set(s.scalars(select(Artifact.kind)))
    assert kinds == {"frame", "mosaic", "probe"}
    assert _digest(original) == before


def test_clearing_waits_for_running_work(setup: Any) -> None:
    control, project, client, _ = setup
    store = JobStore(control.db)
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project_id=project.id,
            kind="analysis",
            params={},
            tasks=[TaskSpec(kind="noop", stage="x", resource_class=ResourceClass.CPU, params={})],
        ),
    )
    assert client.post(f"/api/projects/{project.id}/storage/clear-cache").status_code == 409
    body = {"confirm_name": "Costa Rica 2026"}
    assert (
        client.request("DELETE", f"/api/projects/{project.id}/workspace", json=body).status_code
        == 409
    )
    store.cancel(job)


def test_removal_takes_only_mosaic_data_and_never_the_footage(setup: Any) -> None:
    control, project, client, original = setup
    project.close(checkpoint=False)  # the app's own handles are request-scoped
    before = _digest(original)
    folder = original.parent
    assert (folder / WORKSPACE_DIR).is_dir()
    assert (folder / DESCRIPTOR_NAME).is_file()
    wrong = client.request(
        "DELETE", f"/api/projects/{project.id}/workspace", json={"confirm_name": "Costa"}
    )
    assert wrong.status_code == 422
    ok = client.request(
        "DELETE", f"/api/projects/{project.id}/workspace", json={"confirm_name": "Costa Rica 2026"}
    )
    assert ok.status_code == 200, ok.text
    cleanup.purge_trash()  # the background purge, run here to wait for it
    assert not (folder / WORKSPACE_DIR).exists()
    assert not (folder / DESCRIPTOR_NAME).exists()
    assert sorted(p.name for p in folder.iterdir()) == ["IMG_0001.MOV"], "only the footage is left"
    assert _digest(original) == before
    assert control.project_root(project.id) is None
    assert project.id not in [p["id"] for p in client.get("/api/projects").json()["items"]]
    assert not (app_data_dir() / "trash.json").exists()
    # A worker still holding the project never writes the folder back (checkpoint guard).
    assert project.checkpoint() is None
    assert not (folder / WORKSPACE_DIR).exists()


def test_purge_only_ever_deletes_what_removal_renamed(tmp_path: Path) -> None:
    keep = tmp_path / "Footage"
    keep.mkdir()
    (keep / "a.mov").write_bytes(b"a")
    cleanup._trash_add([keep])  # a corrupted or hand-edited list
    cleanup.purge_trash()
    assert (keep / "a.mov").exists()


def test_diagnostics_tasks_actions_and_a_redacted_bundle(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    control, project, client, _ = setup
    key = "zz-deploy-key-0123456789abcdef"
    monkeypatch.setenv("MOSAIC_SECRET_AI_ANTHROPIC", key)
    job = client.post(f"/api/projects/{project.id}/storage/clear-cache").json()["job_id"]
    with control.db.session() as s, s.begin():
        t = s.scalars(select(Task).where(Task.job_id == job)).one()
        t.status, t.error = "failed", f"boom: called with {key} and sk-ant-api03-ABCDEFGHIJKLMNOP"
        t.params = {"api_key": key, "asset_id": 3}
        tid = t.id
    logs = app_data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "worker.log").write_text(
        f"start\nAuthorization: Bearer abcdefghijklmnop123\nkey={key}\n"
    )

    rows = client.get(
        "/api/diagnostics/tasks", params={"project": project.id, "status": "failed"}
    ).json()
    assert [r["task_id"] for r in rows["items"]] == [tid]
    assert rows["items"][0]["tool"] == "file system"
    assert rows["items"][0]["input"] == "clearing regenerable files"
    assert client.get("/api/diagnostics/tasks", params={"status": "bogus"}).status_code == 422
    detail = client.get(f"/api/diagnostics/tasks/{tid}").json()
    assert key not in json.dumps(detail)
    assert "sk-ant-api03" not in json.dumps(detail)
    assert detail["params"]["api_key"] == "[redacted]"
    assert detail["can_retry"] is True
    assert detail["can_skip"] is True
    assert client.get("/api/diagnostics/tasks/999999").status_code == 404

    bundle = client.post("/api/diagnostics/bundle")
    assert bundle.status_code == 200
    assert "attachment" in bundle.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(bundle.content))
    names = set(z.namelist())
    assert {
        "manifest.json",
        "system.json",
        "settings.json",
        "jobs.json",
        "tasks.json",
        "logs/worker.log",
    } <= names
    for name in names:  # M2 acceptance 3: no secret in the bundle
        text = z.read(name).decode()
        assert key not in text, name
        assert "sk-ant-api03" not in text, name
        assert "abcdefghijklmnop123" not in text, name
    assert "boom: called with [redacted]" in z.read("tasks.json").decode()

    assert client.post(f"/api/diagnostics/tasks/{tid}/skip").json()["skipped"] is True
    assert client.post(f"/api/diagnostics/tasks/{tid}/skip").status_code == 409
    with control.db.session() as s:
        assert s.get(Task, tid).status == "skipped"  # type: ignore[union-attr]
    assert client.post(f"/api/diagnostics/tasks/{tid}/retry").status_code == 409
    assert client.post(f"/api/diagnostics/tasks/{tid}/explode").status_code == 404


def test_retry_resets_a_failed_task_and_what_it_cancelled(setup: Any) -> None:
    control, project, _, _ = setup
    store = JobStore(control.db)
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project_id=project.id,
            kind="test",
            params={},
            tasks=[
                TaskSpec(kind="a", stage="x", resource_class=ResourceClass.CPU, params={}),
                TaskSpec(
                    kind="b", stage="x", resource_class=ResourceClass.CPU, params={}, deps=[0]
                ),
            ],
        ),
    )
    leased = store.lease("w1", "cpu")
    assert leased is not None
    store.fail(leased.id, "w1", "boom", retryable=False)
    tasks = store.tasks(job)
    assert [t.status for t in tasks] == ["failed", "cancelled"]
    assert store.retry_task(tasks[0].id) == 2
    assert [t.status for t in store.tasks(job)] == ["ready", "pending"]
    store.cancel(job)


def test_new_work_waits_while_regenerable_files_are_cleared(setup: Any) -> None:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.storage.projects import ProjectBusyError

    control, project, client, _ = setup
    store = JobStore(control.db)
    job = client.post(f"/api/projects/{project.id}/storage/clear-cache").json()["job_id"]
    with pytest.raises(ProjectBusyError):
        LocalExecutor(store).submit(
            control.local_principal,
            JobSpec(
                project_id=project.id,
                kind="render",
                params={},
                tasks=[
                    TaskSpec(kind="noop", stage="x", resource_class=ResourceClass.CPU, params={})
                ],
            ),
        )
    store.cancel(job)


def test_removal_refuses_what_is_not_its_own(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    control, project, client, original = setup
    folder = original.parent
    # An id from a hand-edited descriptor never reaches app data's other folders.
    for bad in ("..", "", "../..", "01JEDIT/../x"):
        forged = dataclasses.replace(
            project, descriptor=project.descriptor.model_copy(update={"project_id": bad})
        )
        with pytest.raises(cleanup.RemovalError):
            cleanup._owned_dirs(forged)
    # A link where MosAic's folder should be is refused, not followed.
    elsewhere = folder.parent / "Elsewhere"
    elsewhere.mkdir()
    linked = dataclasses.replace(project, outputs_dir=folder / "Link", live_dir=folder / "Link")
    (folder / "Link").symlink_to(elsewhere)
    with pytest.raises(cleanup.RemovalError):
        cleanup._owned_dirs(linked)
    (folder / "Link").unlink()
    assert elsewhere.is_dir()

    # A failed rename moves nothing and keeps the project.
    def fail(*_a: Any) -> None:
        raise PermissionError("busy")

    project.close(checkpoint=False)  # the app's own handles are request-scoped
    monkeypatch.setattr(cleanup.os, "rename", fail)
    body = {"confirm_name": "Costa Rica 2026"}
    r = client.request("DELETE", f"/api/projects/{project.id}/workspace", json=body)
    assert r.status_code == 409
    assert "nothing was removed" in r.json()["detail"]
    assert (folder / WORKSPACE_DIR).is_dir()
    assert (folder / DESCRIPTOR_NAME).is_file()
    assert control.project_root(project.id) is not None
    assert (
        not (app_data_dir() / "trash.json").exists()
        or json.loads((app_data_dir() / "trash.json").read_text()) == []
    )
    assert client.get(f"/api/projects/{project.id}/storage").status_code == 200


def test_removal_waits_while_the_project_is_open_elsewhere(setup: Any) -> None:
    from mosaic.storage.locks import FileLock
    from mosaic.storage.projects import OPEN_LOCK

    control, project, client, original = setup
    project.close(checkpoint=False)
    other = FileLock(project.live_dir / OPEN_LOCK, exclusive=False, blocking=False)  # a worker
    try:
        r = client.request(
            "DELETE",
            f"/api/projects/{project.id}/workspace",
            json={"confirm_name": "Costa Rica 2026"},
        )
        assert r.status_code == 409
        assert "open in MosAic elsewhere" in r.json()["detail"]
        assert (original.parent / WORKSPACE_DIR).is_dir()
        assert control.project_root(project.id) is not None
    finally:
        other.release()


def test_skip_after_a_real_failure_lets_the_job_finish(setup: Any) -> None:
    control, project, _, _ = setup
    store = JobStore(control.db)
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project_id=project.id,
            kind="test",
            params={},
            tasks=[
                TaskSpec(kind="a", stage="x", resource_class=ResourceClass.CPU, params={}),
                TaskSpec(
                    kind="b", stage="x", resource_class=ResourceClass.CPU, params={}, deps=[0]
                ),
            ],
        ),
    )
    a = store.lease("w1", "cpu")
    assert a is not None
    store.fail(a.id, "w1", "boom", retryable=False)
    assert store.job(job).status == "failed"  # type: ignore[union-attr]
    assert store.skip_failed(a.id, "skipped from Diagnostics")
    assert [t.status for t in store.tasks(job)] == ["skipped", "ready"]
    b = store.lease("w1", "cpu")
    assert b is not None
    store.complete(b.id, "w1")
    assert store.job(job).status == "done"  # type: ignore[union-attr]
    # A job the owner cancelled stays cancelled.
    job2 = store.create_job(
        control.local_principal,
        JobSpec(
            project_id=project.id,
            kind="test",
            params={},
            tasks=[TaskSpec(kind="a", stage="x", resource_class=ResourceClass.CPU, params={})],
        ),
    )
    store.cancel(job2)  # the owner cancelled it before it ran
    c = store.tasks(job2)[0]
    assert c.status == "cancelled"
    assert store.retry_task(c.id) == 0
    assert not store.skip_failed(c.id, "x")


def test_bundle_redacts_the_master_key_and_docker_secrets_but_keeps_counts(
    setup: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    control, project, client, _ = setup
    master = "m" * 8 + "-MASTER-0123456789abcdefghijklmn"
    docker = tmp_path / "secrets"
    docker.mkdir()
    (docker / "mosaic_ai_openai").write_text("dk-docker-secret-value-42\n")
    monkeypatch.setenv("MOSAIC_MASTER_KEY", master)
    monkeypatch.setenv("MOSAIC_DOCKER_SECRETS_DIR", str(docker))
    job = client.post(f"/api/projects/{project.id}/storage/clear-cache").json()["job_id"]
    with control.db.session() as s, s.begin():
        t = s.scalars(select(Task).where(Task.job_id == job)).one()
        t.status = "failed"
        t.error = f"master {master}; docker dk-docker-secret-value-42; https://bob:hunter2pass@nas.local/x"
        t.params = {"max_tokens": 8000, "tokens_in": 5, "master_key": master}
        tid = t.id
    detail = client.get(f"/api/diagnostics/tasks/{tid}").json()
    assert detail["params"] == {"max_tokens": 8000, "tokens_in": 5, "master_key": "[redacted]"}
    assert "hunter2pass" not in detail["error"]
    z = zipfile.ZipFile(io.BytesIO(client.post("/api/diagnostics/bundle").content))
    for name in z.namelist():
        text = z.read(name).decode()
        for secret in (master, "dk-docker-secret-value-42", "hunter2pass"):
            assert secret not in text, (name, secret)
    store = JobStore(control.db)
    store.cancel(job)


def test_rename_changes_the_name_not_the_folder(setup: Any) -> None:
    from mosaic.storage.descriptor import read_descriptor

    _, project, client, original = setup
    folder = original.parent
    r = client.patch(f"/api/projects/{project.id}", json={"name": "  Costa   Rica 2026 · family "})
    assert r.status_code == 200
    assert r.json()["name"] == "Costa Rica 2026 · family"
    d = read_descriptor(folder)
    assert d is not None
    assert d.name == "Costa Rica 2026 · family"
    assert folder.name == "Trip"
    listed = {p["id"]: p["name"] for p in client.get("/api/projects").json()["items"]}
    assert listed[project.id] == "Costa Rica 2026 · family"
    assert client.patch(f"/api/projects/{project.id}", json={"name": "   "}).status_code == 422
    assert client.patch(f"/api/projects/{project.id}", json={"name": "x" * 121}).status_code == 422
