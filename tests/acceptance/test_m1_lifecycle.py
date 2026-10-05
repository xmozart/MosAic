"""M1 acceptance 3: moving a trip folder to another disk and reopening relinks every file
with no re-analysis (ADR 0023). Also: a file renamed inside the folder keeps its record."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.app.main import create_app
from mosaic.app.services import Services
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.pipeline import submit_analysis
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import TaskEvent
from mosaic.storage.models_project import Asset, MediaFile
from mosaic.storage.projects import init_project
from tests.support.runner import run_job

pytestmark = [pytest.mark.acceptance, pytest.mark.models]

FILES = ("A001_basic.mp4", "A002_basic.mp4", "GX010042.MP4", "GX020042.MP4", "speech.mp4")
ANALYSIS = {
    "media.proxy",
    "media.visual",
    "audio.analyze",
    "library.embed",
    "library.segments",
    "library.mosaics",
    "library.vision",
    "media.probe",
}


def _copy_without_times(src: Path, dst: Path) -> None:
    """Like copying to another disk with a tool that does not keep modification times."""
    dst.mkdir(parents=True)
    for here, _dirs, files in os.walk(src):
        rel = Path(here).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copyfile(Path(here) / f, dst / rel / f)


def _records(s: object) -> dict[str, tuple[int, str, int | None]]:
    rows = s.scalars(select(MediaFile))  # type: ignore[attr-defined]
    return {m.rel_path: (m.id, m.fingerprint, m.asset_id) for m in rows}


def _ran(control: ControlDB, job: int) -> set[str]:
    """Task kinds that actually ran (not found done by their key)."""
    store = JobStore(control.db)
    kinds = {t.id: t.kind for t in store.tasks(job)}
    with control.db.session() as s:
        started = set(
            s.scalars(
                select(TaskEvent.task_id).where(
                    TaskEvent.task_id.in_(list(kinds)), TaskEvent.event == "started"
                )
            )
        )
    return {kinds[t] for t in started}


def test_moved_folder_relinks_without_reanalysis(corpus_dir: Path, tmp_path: Path) -> None:
    disk_a = tmp_path / "disk-a" / "Trip"
    disk_a.mkdir(parents=True)
    for name in FILES:
        shutil.copy(corpus_dir / name, disk_a / name)
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "all", "fake", "fake")
    project = init_project(control, me, disk_a)
    pid = project.id
    executor = LocalExecutor(JobStore(control.db))
    assert run_job(control, submit_analysis(executor, me, project), timeout=1200) == "done"
    with project.db.session() as s:
        before = {
            m.rel_path: (m.id, m.fingerprint, m.asset_id) for m in s.scalars(select(MediaFile))
        }
    project.close()

    disk_b = tmp_path / "disk-b" / "Trip"
    _copy_without_times(disk_a, disk_b)
    shutil.rmtree(disk_a)

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    r = client.post(f"/api/projects/{pid}/relink")
    assert r.status_code == 409, "the old folder is gone: the UI asks where it is"
    calls = len(fake.CALLS)
    r = client.post(f"/api/projects/{pid}/relink", json={"choose_folder": str(disk_b)})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    assert run_job(control, job, timeout=1200) == "done"
    assert control.project_root(pid) == disk_b.resolve()
    assert fake.CALLS[calls:] == [], "no AI call"
    assert not (_ran(control, job) & ANALYSIS), _ran(control, job)
    scan = next(t for t in JobStore(control.db).tasks(job) if t.kind == "analysis.scan")
    assert scan.result["relinked"] == len(before)
    from mosaic.storage.projects import open_project

    moved = open_project(control, me, disk_b, read_only=True)
    with moved.db.session() as s:
        after = {
            m.rel_path: (m.id, m.fingerprint, m.asset_id) for m in s.scalars(select(MediaFile))
        }
        assert {m.status for m in s.scalars(select(MediaFile))} <= {"ok", "unsupported"}
    moved.close()
    assert after == before, "every file is the same record, fingerprint and asset"


def test_a_renamed_file_keeps_its_record(corpus_dir: Path, tmp_path: Path) -> None:
    trip = tmp_path / "Trip"
    trip.mkdir()
    shutil.copy(corpus_dir / "A001_basic.mp4", trip / "A001_basic.mp4")
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "all", "fake", "fake")
    project = init_project(control, me, trip)
    executor = LocalExecutor(JobStore(control.db))
    assert run_job(control, submit_analysis(executor, me, project), timeout=600) == "done"
    with project.db.session() as s:
        row = s.scalar(select(MediaFile).where(MediaFile.rel_path == "A001_basic.mp4"))
        assert row is not None
        rid, fp, aid = row.id, row.fingerprint, row.asset_id
    (trip / "day1").mkdir()
    (trip / "A001_basic.mp4").rename(trip / "day1" / "harbour.mp4")
    job = submit_analysis(executor, me, project)
    assert run_job(control, job, timeout=600) == "done"
    assert _ran(control, job) & ANALYSIS <= {"media.probe"}, "only the probe runs again"
    with project.db.session() as s:
        moved = s.get(MediaFile, rid)
        assert moved is not None
        assert moved.rel_path == "day1/harbour.mp4"
        assert moved.fingerprint == fp
        assert moved.status == "ok"
        assert moved.asset_id == aid, "the asset (ratings, decisions, edits) follows the file"
        assert s.scalar(select(MediaFile).where(MediaFile.status == "missing")) is None
        asset = s.get(Asset, aid)
        assert asset is not None
        assert asset.status == "ok"
    project.close()
