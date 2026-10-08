"""Split and external placement (M1 step 6, ADR 0022): snapshots, seeding, generations,
relocation safety and folder fingerprints."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mosaic.storage import projects as projects_mod
from mosaic.storage import sqlite_engine
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import ProjectMeta
from mosaic.storage.placement import Placement
from mosaic.storage.projects import (
    PROJECT_DB,
    SNAPSHOT_META,
    ProjectBusyError,
    SnapshotConflictError,
    folder_fingerprint,
    init_project,
    open_project,
)


def _note(project: projects_mod.Project, key: str, value: str) -> None:
    with project.write() as s:
        s.merge(ProjectMeta(key=key, value=value))


def _value(project: projects_mod.Project, key: str) -> str | None:
    with project.db.session() as s:
        row = s.get(ProjectMeta, key)
        return row.value if row else None


@pytest.fixture
def snapshots(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    made: list[Path] = []
    real = projects_mod._publish

    def counting(scratch: Path, dest: Path) -> None:
        made.append(dest)
        real(scratch, dest)

    monkeypatch.setattr(projects_mod, "_publish", counting)
    return made


def test_checkpoint_only_when_changed(tmp_path: Path, snapshots: list[Path]) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    assert p.checkpoint() is not None
    assert p.checkpoint() is None, "nothing changed"
    p.close()
    assert len(snapshots) == 1
    # Read-only opens (as an API GET does) never snapshot.
    for _ in range(3):
        q = open_project(control, control.local_principal, tmp_path)
        assert _value(q, "project_id") == p.id
        q.close()
    assert len(snapshots) == 1
    q = open_project(control, control.local_principal, tmp_path)
    _note(q, "x", "1")
    q.close()
    assert len(snapshots) == 2, "a write since the last snapshot"
    meta = json.loads((tmp_path / "MosAic" / SNAPSHOT_META).read_text())
    assert meta == {"project_id": p.id, "generation": 2, "written_at": meta["written_at"]}


def test_snapshot_is_a_self_contained_copy(tmp_path: Path) -> None:
    import sqlite3

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    _note(p, "x", "after the last task")
    p.close()
    copy = tmp_path / "copy.db"
    shutil.copy(tmp_path / "MosAic" / PROJECT_DB, copy)
    con = sqlite3.connect(copy)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        row = con.execute("SELECT value FROM project_meta WHERE key='x'").fetchone()
        assert row[0] == "after the last task", "close snapshots writes made after any task"
    finally:
        con.close()
    assert not list((tmp_path / "MosAic").glob("*.part"))


def test_other_computer_round_trip_and_conflict(tmp_path: Path) -> None:
    """A writes and closes; B (no live DB) is seeded and writes; A, unchanged since its
    snapshot, picks up B's work. If A had changes too, it is refused, not overwritten."""
    control = ControlDB()
    me = control.local_principal
    a = init_project(control, me, tmp_path, placement=Placement.SPLIT)
    live = a.live_dir
    _note(a, "who", "A")
    a.close()
    kept = tmp_path.parent / "computer-A"
    shutil.copytree(live, kept)  # A's live directory, as A keeps it
    shutil.rmtree(live)
    b = open_project(control, me, tmp_path)  # B: seeded from the snapshot
    assert _value(b, "who") == "A"
    _note(b, "who", "B")
    b.close()
    shutil.rmtree(live)
    shutil.copytree(kept, live)  # back on A, with A's older live DB
    a2 = open_project(control, me, tmp_path)
    assert _value(a2, "who") == "B", "A's unchanged DB is replaced by the newer snapshot"
    assert list(live.glob("replaced-*/project.db")), "the old DB is kept aside"
    a2.close()
    # Conflict: A changed locally while the folder got a newer snapshot from B.
    shutil.rmtree(live)
    shutil.copytree(kept, live)
    with sqlite_conn(live / PROJECT_DB) as con:
        con.execute("INSERT OR REPLACE INTO project_meta VALUES ('who', 'A2')")
    with pytest.raises(SnapshotConflictError):
        open_project(control, me, tmp_path)


class sqlite_conn:  # noqa: N801 - tiny context manager
    def __init__(self, path: Path) -> None:
        import sqlite3

        self.con = sqlite3.connect(path)

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self.con

    def __exit__(self, *exc: object) -> None:
        self.con.commit()
        self.con.close()


def test_newer_snapshot_is_never_overwritten(tmp_path: Path, snapshots: list[Path]) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    p.checkpoint()
    meta = tmp_path / "MosAic" / SNAPSHOT_META
    newer = json.loads(meta.read_text()) | {"generation": 99}
    meta.write_text(json.dumps(newer))
    _note(p, "x", "1")
    assert p.checkpoint() is None
    assert json.loads(meta.read_text())["generation"] == 99
    p.close()


def test_snapshot_of_another_project_is_not_used(tmp_path: Path) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    _note(p, "x", "mine")
    p.close()
    meta = tmp_path / "MosAic" / SNAPSHOT_META
    meta.write_text(json.dumps(json.loads(meta.read_text()) | {"project_id": "OTHER"}))
    shutil.rmtree(p.live_dir)
    q = open_project(control, control.local_principal, tmp_path)
    assert _value(q, "x") is None, "a snapshot copied from another project never seeds"
    q.close()


def test_relocation_is_refused_while_open(tmp_path: Path) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with pytest.raises(ProjectBusyError):
        init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    p.close()
    q = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    q.close()


def test_relocation_crash_before_the_descriptor_loses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    _note(p, "x", "kept")
    p.close()

    def crash(*_a: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(projects_mod, "_save_descriptor", crash)
    with pytest.raises(OSError, match="power cut"):
        init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    monkeypatch.undo()
    q = open_project(control, control.local_principal, tmp_path)
    assert q.placement is Placement.IN_FOLDER
    assert _value(q, "x") == "kept", "the old copy is the project until the descriptor moves"
    q.close()


def test_relocation_to_and_from_external(tmp_path: Path) -> None:
    control = ControlDB()
    me = control.local_principal
    (tmp_path / "clip.mp4").write_bytes(b"original")
    p = init_project(control, me, tmp_path)
    _note(p, "x", "1")
    p.close()
    ext = init_project(control, me, tmp_path, placement=Placement.EXTERNAL)
    assert not (tmp_path / ".mosaic-project.json").exists()
    assert not (tmp_path / "MosAic" / PROJECT_DB).exists()
    assert _value(ext, "x") == "1"
    pid = ext.id
    ext.close()
    again = open_project(control, me, tmp_path)  # found by path
    assert again.id == pid
    again.close()
    back = init_project(control, me, tmp_path, placement=Placement.IN_FOLDER)
    assert back.id == pid
    assert _value(back, "x") == "1"
    assert (tmp_path / ".mosaic-project.json").is_file()
    back.close()
    assert (tmp_path / "clip.mp4").read_bytes() == b"original"


def test_folder_fingerprints(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert folder_fingerprint(empty) is None
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / ".DS_Store").write_bytes(b"x")
    assert folder_fingerprint(hidden) is None
    a = tmp_path / "a"
    (a / "DCIM").mkdir(parents=True)
    (a / "DCIM" / "1.mp4").write_bytes(b"12")
    (a / "2.mp4").write_bytes(b"1")
    b = tmp_path / "b"
    shutil.copytree(a, b)
    assert folder_fingerprint(a) == folder_fingerprint(b) is not None
    (b / "2.mp4").write_bytes(b"12")
    assert folder_fingerprint(a) != folder_fingerprint(b)


def test_identical_existing_folders_are_not_confused(tmp_path: Path) -> None:
    """Two copies of one card that both exist are two projects, not one."""
    control = ControlDB()
    me = control.local_principal
    a = tmp_path / "a"
    a.mkdir()
    (a / "1.mp4").write_bytes(b"12")
    b = tmp_path / "b"
    shutil.copytree(a, b)
    pa = init_project(control, me, a, placement=Placement.EXTERNAL)
    pa.close()
    pb = init_project(control, me, b, placement=Placement.EXTERNAL)
    assert pb.id != pa.id
    pb.close()
    assert open_project(control, me, a).id == pa.id


def test_open_hook_sees_every_sqlite_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []
    monkeypatch.setattr(sqlite_engine, "OPEN_HOOKS", [seen.append])
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    _note(p, "x", "1")
    p.close()
    assert any(s.name == PROJECT_DB for s in seen)
    assert all(not s.resolve().is_relative_to(tmp_path.resolve()) for s in seen), seen


def test_a_failed_snapshot_never_fails_the_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.library.summaries import submit_summaries
    from tests.support.runner import run_job

    def broken(self: projects_mod.Project) -> None:
        raise sqlite3.OperationalError("database is locked")

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    monkeypatch.setattr(projects_mod.Project, "checkpoint", broken)
    job = submit_summaries(LocalExecutor(JobStore(control.db)), control.local_principal, p)
    assert run_job(control, job, timeout=120) == "done"
    assert {t.status for t in JobStore(control.db).tasks(job)} == {"done"}
    p.close()  # close tolerates it too


def test_a_newer_snapshot_never_replaces_a_db_open_elsewhere(tmp_path: Path) -> None:
    control = ControlDB()
    me = control.local_principal
    p = init_project(control, me, tmp_path, placement=Placement.SPLIT)
    _note(p, "x", "1")
    p.checkpoint()
    meta = tmp_path / "MosAic" / SNAPSHOT_META
    meta.write_text(json.dumps(json.loads(meta.read_text()) | {"generation": 99}))
    q = open_project(control, me, tmp_path)  # p (a worker, say) still has it open
    _note(p, "y", "kept")
    assert _value(q, "y") == "kept", "both handles use the same live DB"
    assert not list(p.live_dir.glob("replaced-*")), "nothing was moved aside"
    q.close(checkpoint=False)
    p.close()


def test_relocating_away_from_split_takes_the_newer_snapshot(tmp_path: Path) -> None:
    control = ControlDB()
    me = control.local_principal
    a = init_project(control, me, tmp_path, placement=Placement.SPLIT)
    live = a.live_dir
    a.close()
    kept = tmp_path.parent / "computer-A-2"
    shutil.copytree(live, kept)
    shutil.rmtree(live)
    b = open_project(control, me, tmp_path)  # another computer
    _note(b, "who", "B")
    b.close()
    shutil.rmtree(live)
    shutil.copytree(kept, live)  # back on A: stale, unchanged since its snapshot
    home = init_project(control, me, tmp_path, placement=Placement.IN_FOLDER)
    assert _value(home, "who") == "B", "B's work survives the move"
    home.close()


def test_seeding_then_closing_publishes_nothing(tmp_path: Path, snapshots: list[Path]) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    _note(p, "x", "1")
    p.close()
    shutil.rmtree(p.live_dir)
    count = len(snapshots)
    q = open_project(control, control.local_principal, tmp_path)
    q.close()
    assert len(snapshots) == count


def test_concurrent_opens_wait_for_each_other(tmp_path: Path) -> None:
    import threading
    import time

    from mosaic.storage.locks import FileLock

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path, placement=Placement.SPLIT)
    live = p.live_dir
    p.close()
    held = FileLock(live / projects_mod.OPEN_LOCK, exclusive=True, blocking=True)
    threading.Timer(0.2, held.release).start()  # another opener, seeding for a moment
    start = time.monotonic()
    q = open_project(control, control.local_principal, tmp_path)
    assert time.monotonic() - start >= 0.15, "it waited instead of failing"
    q.close()


def test_project_errors_are_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.routers import edits as edits_router
    from mosaic.app.services import Services

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    pid = p.id
    p.close()

    def conflict(*_a: object, **_k: object) -> None:
        raise SnapshotConflictError("changed here and elsewhere")

    monkeypatch.setattr(edits_router, "open_project", conflict)
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    r = TestClient(app).get(f"/api/projects/{pid}/trip-context")
    assert r.status_code == 409
    assert "elsewhere" in r.json()["detail"]


@pytest.mark.parametrize("ftype", ["virtiofs", "fakeowner", "fuse.grpcfuse", "osxfs"])
def test_a_folder_shared_in_from_the_host_never_holds_a_live_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ftype: str
) -> None:
    """Invariant 2, ADR 0055: Docker Desktop shares a host folder that may be a NAS or a
    cloud-synced folder; from inside it looks local, so it is treated as a network share."""
    from mosaic.storage import placement

    monkeypatch.setattr(placement, "fs_type", lambda _p: ftype)
    c = placement.classify(tmp_path)
    assert c.fs_class is placement.FsClass.NETWORK
    assert c.placement is Placement.SPLIT
    with pytest.raises(placement.PlacementRefusedError):
        placement.assert_live_db_allowed(tmp_path / "MosAic" / PROJECT_DB)


def test_the_server_image_keeps_live_dbs_in_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.core.paths import app_data_dir
    from mosaic.storage import placement

    monkeypatch.setattr(placement, "fs_type", lambda _p: "ext4")
    assert placement.classify(tmp_path).placement is Placement.IN_FOLDER
    monkeypatch.setenv(placement.ENV_FOLDER_DB, "never")
    c = placement.classify(tmp_path)
    assert c.fs_class is placement.FsClass.LOCAL
    assert c.placement is Placement.SPLIT
    assert "stays in app data" in c.reason
    with pytest.raises(placement.PlacementRefusedError):
        placement.assert_live_db_allowed(tmp_path / "MosAic" / PROJECT_DB)
    placement.assert_live_db_allowed(app_data_dir() / "projects" / "x" / PROJECT_DB)
    # A new project there is split: its live DB in app data, nothing live in the folder.
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    assert project.placement is Placement.SPLIT
    assert app_data_dir().resolve() in project.live_dir.resolve().parents
    assert not (tmp_path / "MosAic" / f"{PROJECT_DB}-wal").exists()
    project.close()


def test_a_trip_made_in_folder_moves_its_live_db_when_opened_by_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.core.paths import app_data_dir
    from mosaic.storage import placement

    monkeypatch.setattr(placement, "fs_type", lambda _p: "ext4")
    control = ControlDB()
    made = init_project(control, control.local_principal, tmp_path)  # on the desktop
    assert made.placement is Placement.IN_FOLDER
    _note(made, "kept", "yes")
    made.close()
    monkeypatch.setenv(placement.ENV_FOLDER_DB, "never")  # the server image
    with pytest.raises(placement.PlacementRefusedError):
        init_project(control, control.local_principal, tmp_path, placement=Placement.IN_FOLDER)
    moved = init_project(control, control.local_principal, tmp_path)
    assert moved.placement is Placement.SPLIT
    assert app_data_dir().resolve() in moved.live_dir.resolve().parents
    with moved.db.session() as s:
        row = s.get(ProjectMeta, "kept")
        assert row is not None
        assert row.value == "yes"  # nothing was lost on the way
    moved.close()
