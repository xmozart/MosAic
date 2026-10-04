"""Worker runtime: in-process (threads) and the kill -9 resume acceptance (M0 #2)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mosaic.jobs import registry
from mosaic.jobs.model import JobSpec, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.jobs.worker import Worker
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import init_project

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(registry.ENV_PLUGINS, "tests.support.handlers")
    registry.load_handlers()


def _run_worker_until(worker: Worker, store: JobStore, job: int, timeout: float = 30) -> None:
    th = threading.Thread(target=worker.run, daemon=True)
    th.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = store.job(job)
        if j is not None and j.status in ("done", "failed", "cancelled"):
            break
        time.sleep(0.05)
    worker.stop.set()
    th.join(timeout=10)


@pytest.mark.usefixtures("handlers")
def test_worker_runs_dag_with_fanout_retry_skip_and_permanent(tmp_path: Path) -> None:
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    store = JobStore(control.db)
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project.id,
            "test",
            tasks=[
                TaskSpec("test.fanout", "plan", params={"n": 5}),
                TaskSpec("test.flaky", "s"),
                TaskSpec("test.skip", "s"),
                TaskSpec("test.sleep", "s", deps=[2], output_key="after-skip"),
            ],
        ),
    )
    _run_worker_until(Worker(control, slots={"cpu": 3}), store, job)
    by_kind: dict[str, list[str]] = {}
    for t in store.tasks(job):
        by_kind.setdefault(t.kind, []).append(t.status)
    assert by_kind["test.sleep"] == ["done"] * 6
    assert by_kind["test.flaky"] == ["done"]
    assert by_kind["test.skip"] == ["skipped"]
    j = store.job(job)
    assert j is not None
    assert j.status == "done"

    perm = store.create_job(
        control.local_principal, JobSpec(project.id, "t2", tasks=[TaskSpec("test.permanent", "s")])
    )
    _run_worker_until(Worker(control, slots={"cpu": 1}), store, perm)
    t = store.tasks(perm)[0]
    assert (t.status, t.attempts) == ("failed", 1)
    project.close()


@pytest.mark.usefixtures("handlers")
def test_existing_artifacts_mark_tasks_done_without_work(tmp_path: Path) -> None:
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    store = JobStore(control.db)
    specs = [TaskSpec("test.sleep", "s", output_key=f"k-{i}") for i in range(4)]
    first = store.create_job(control.local_principal, JobSpec(project.id, "a", tasks=specs))
    _run_worker_until(Worker(control, slots={"cpu": 2}), store, first)
    again = store.create_job(
        control.local_principal,
        JobSpec(
            project.id,
            "a",
            tasks=[TaskSpec("test.sleep", "s", output_key=f"k-{i}") for i in range(4)],
        ),
    )
    _run_worker_until(Worker(control, slots={"cpu": 2}), store, again)
    assert {e.event for e in store.events(again)} == {"leased", "skipped_existing"}
    project.close()


def _spawn_worker(env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "mosaic.jobs.worker"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_resume_after_kill_9_does_not_redo_finished_tasks(tmp_path: Path) -> None:
    """M0 acceptance 2."""
    env = {
        **os.environ,
        registry.ENV_PLUGINS: "tests.support.handlers",
        "MOSAIC_LEASE_MS": "1500",
        "PYTHONPATH": str(ROOT),
    }
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    store = JobStore(control.db)
    n = 40
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project.id,
            "analysis",
            tasks=[
                TaskSpec("test.sleep", "s", params={"ms": 150}, output_key=f"r-{i}")
                for i in range(n)
            ],
        ),
    )

    proc = _spawn_worker(env)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        p = store.progress(job)
        if p is not None and p.done >= 10:
            break
        time.sleep(0.05)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    done_before = {t.id for t in store.tasks(job, "done")}
    assert 10 <= len(done_before) < n, "kill must land mid-analysis"

    proc2 = _spawn_worker(env)
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            j = store.job(job)
            if j is not None and j.status == "done":
                break
            time.sleep(0.1)
    finally:
        proc2.terminate()
        proc2.wait(timeout=20)
    assert {t.status for t in store.tasks(job)} == {"done"}
    started: dict[int, int] = {}
    for e in store.events(job):
        if e.event == "started":
            started[e.task_id] = started.get(e.task_id, 0) + 1
    # Tasks finished before the kill were never started again.
    assert all(started[tid] == 1 for tid in done_before)
    assert all(started.get(t.id, 0) >= 1 for t in store.tasks(job))
    project.close()
