"""M1 acceptance 1 and 2: storage placement (ARCHITECTURE.md §4, ADR 0022).

1. A project on an SMB share and one in an iCloud Drive folder both open with placement
   ``split``. No SQLite file is ever opened read-write on those paths (asserted through
   the DB layer's open hook). A snapshot appears in the folder after each checkpoint.
2. A read-only folder opens with placement ``external`` and full functionality: analysis,
   an edit and a render.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Any

import pytest

from mosaic.editing.request import EditRequest
from mosaic.editing.service import create_edit, get_version, submit_generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.pipeline import submit_analysis
from mosaic.render.service import create_render, get_render, submit_render
from mosaic.render.tasks import output_path
from mosaic.storage import placement, sqlite_engine
from mosaic.storage import projects as projects_mod
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.placement import Placement
from mosaic.storage.projects import PROJECT_DB, init_project, open_project
from tests.support.runner import run_job

pytestmark = [pytest.mark.acceptance, pytest.mark.models]

FILES = ("A001_basic.mp4", "A002_basic.mp4", "GX010042.MP4", "GX020042.MP4")


def _trip(corpus_dir: Path, dest: Path) -> Path:
    dest.mkdir(parents=True)
    for name in FILES:
        shutil.copy(corpus_dir / name, dest / name)
    return dest


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    paths: list[Path] = []
    monkeypatch.setattr(sqlite_engine, "OPEN_HOOKS", [lambda p: paths.append(p.resolve())])
    return paths


def _analyze(control: ControlDB, project: Any) -> None:
    executor = LocalExecutor(JobStore(control.db))
    job = submit_analysis(executor, control.local_principal, project)
    assert run_job(control, job, timeout=1200) == "done"


def _edit(control: ControlDB, project: Any) -> int:
    me = control.local_principal
    executor = LocalExecutor(JobStore(control.db))
    edit_id = create_edit(project, EditRequest(duration_s=20), control, me)
    assert run_job(control, submit_generate(executor, me, project, edit_id), timeout=600) == "done"
    return edit_id


def _analyze_and_edit(control: ControlDB, project: Any) -> int:
    _analyze(control, project)
    return _edit(control, project)


def _inspect(snapshot: Path, tmp: Path) -> tuple[str, int]:
    """Copy the snapshot out of the folder and open the copy: integrity, journal mode and
    the number of edit versions."""
    import hashlib
    import sqlite3

    copy = tmp / f"inspect-{hashlib.sha256(snapshot.read_bytes()).hexdigest()[:8]}.db"
    shutil.copy(snapshot, copy)
    con = sqlite3.connect(copy)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        versions = con.execute("SELECT count(*) FROM edit_version").fetchone()[0]
    finally:
        con.close()
    return hashlib.sha256(snapshot.read_bytes()).hexdigest(), int(versions)


@pytest.mark.parametrize("kind", ["smb", "icloud"])
def test_network_and_cloud_folders_are_split(
    kind: str,
    corpus_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened: list[Path],
) -> None:
    if kind == "smb":
        trip = _trip(corpus_dir, tmp_path / "share" / "Trip").resolve()
        real = placement.fs_type
        monkeypatch.setattr(
            placement, "fs_type", lambda p: "smbfs" if Path(p).is_relative_to(trip) else real(p)
        )
    else:
        home = tmp_path / "home"
        trip = _trip(corpus_dir, home / "Library" / "Mobile Documents" / "Trip").resolve()
        monkeypatch.setenv("HOME", str(home))
    control = ControlDB()
    ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
    project = init_project(control, control.local_principal, trip)
    assert project.placement is Placement.SPLIT
    assert (trip / ".mosaic-project.json").is_file()
    assert not project.live_dir.is_relative_to(trip)
    snapshot = trip / "MosAic" / PROJECT_DB

    published: list[Path] = []
    real_publish = projects_mod._publish
    monkeypatch.setattr(
        projects_mod, "_publish", lambda a, b: (published.append(b), real_publish(a, b))
    )
    _analyze(control, project)
    assert snapshot.is_file(), "a snapshot after the analysis checkpoints"
    after_analysis, versions = _inspect(snapshot, tmp_path)
    assert versions == 0
    # One snapshot per checkpointing stage at most, never one per file or clip.
    assert 1 <= len(published) <= 5, published
    edit_id = _edit(control, project)
    after_edit, versions = _inspect(snapshot, tmp_path)
    assert after_edit != after_analysis, "the edit commit is a checkpoint"
    assert versions == 1, "the snapshot holds the committed edit"
    assert get_version(project, edit_id) is not None
    exports = list((trip / "MosAic" / "edits").rglob("*.json"))
    assert exports, "edit JSON is written to the folder"
    assert not (trip / "MosAic" / "cache").exists(), "proxies and cache stay local"
    project.close()

    # Invariant 2: nothing on the share or in iCloud was opened as a live database.
    assert opened
    assert not [p for p in opened if p.is_relative_to(trip)], opened

    # The folder opened on another computer: the snapshot seeds a new live DB.
    shutil.rmtree(project.live_dir)
    again = open_project(control, control.local_principal, trip)
    try:
        assert again.id == project.id
        assert again.placement is Placement.SPLIT
        assert get_version(again, edit_id) is not None, "the edit came with the snapshot"
    finally:
        again.close()
    assert not [p for p in opened if p.is_relative_to(trip)]


def _read_only(path: Path) -> None:
    for here, _dirs, files in os.walk(path):
        for f in files:
            os.chmod(Path(here) / f, stat.S_IRUSR | stat.S_IRGRP)
        os.chmod(here, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)


def _writable(path: Path) -> None:
    for here, _dirs, files in os.walk(path):
        os.chmod(here, stat.S_IRWXU)
        for f in files:
            os.chmod(Path(here) / f, stat.S_IRUSR | stat.S_IWUSR)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_read_only_folder_is_external_with_full_functionality(
    corpus_dir: Path, tmp_path: Path
) -> None:
    trip = _trip(corpus_dir, tmp_path / "ro" / "Trip").resolve()
    _read_only(trip)
    try:
        control = ControlDB()
        me = control.local_principal
        ConfigService(control).set_provider(me, "all", "fake", "fake")
        project = init_project(control, me, trip)
        assert project.placement is Placement.EXTERNAL
        assert sorted(p.name for p in trip.iterdir()) == sorted(FILES), "nothing written"
        edit_id = _analyze_and_edit(control, project)
        v = get_version(project, edit_id)
        rid = create_render(project, edit_id, v.version, "preview")
        job = submit_render(LocalExecutor(JobStore(control.db)), me, project, rid)
        assert run_job(control, job, timeout=900) == "done"
        r = get_render(project, rid)
        assert r is not None
        out = output_path(project.workspace, r)
        assert out.is_file()
        assert not out.is_relative_to(trip)
        pid = project.id
        project.close()

        # Re-opened by path, then found again by its fingerprint after a move.
        assert open_project(control, me, trip).id == pid
        moved = tmp_path / "elsewhere" / "Trip"
        moved.parent.mkdir()
        _writable(trip)
        shutil.move(trip, moved)  # the card copied to another disk, the original gone
        _read_only(moved)
        again = open_project(control, me, moved)
        assert again.id == pid
        assert get_version(again, edit_id) is not None
        again.close()
        _writable(moved)
    finally:
        if trip.exists():
            _writable(trip)
