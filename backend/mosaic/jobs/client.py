"""Helpers for the CLI and API: find or start the worker, follow a job to completion."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable

from sqlalchemy import select

from mosaic.core.paths import app_data_dir
from mosaic.jobs.model import JOB_TERMINAL, JobProgress
from mosaic.jobs.store import JobStore, now_ms
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import WorkerRecord

WORKER_STALE_MS = 10_000


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_worker(control: ControlDB) -> WorkerRecord | None:
    with control.db.session() as s:
        for rec in s.scalars(select(WorkerRecord)):
            if now_ms() - rec.heartbeat_ms < WORKER_STALE_MS and _pid_alive(rec.pid):
                return rec
    return None


def start_worker(exit_when_idle_s: float = 20.0) -> subprocess.Popen[bytes]:
    """Start a detached worker process that exits when idle. Logs go to app-data/logs."""
    logs = app_data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "worker.log").open("ab") as out:  # the child keeps its own descriptor
        return subprocess.Popen(
            [sys.executable, "-m", "mosaic.jobs.worker", "--exit-when-idle", str(exit_when_idle_s)],
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )


REGISTRATION_GRACE_S = 15.0


def ensure_worker(control: ControlDB) -> subprocess.Popen[bytes] | None:
    """Start a worker unless a live one is registered. Returns the new process, if any."""
    if live_worker(control) is None:
        return start_worker()
    return None


def wait_for_job(
    store: JobStore,
    job_id: int,
    on_progress: Callable[[JobProgress], None] | None = None,
    poll_s: float = 0.5,
    timeout_s: float | None = None,
    control: ControlDB | None = None,
    worker: subprocess.Popen[bytes] | None = None,
) -> JobProgress:
    """Poll until the job is terminal.

    With ``control``, a worker is restarted only when the one we started has exited, or
    when no live worker has registered within ``REGISTRATION_GRACE_S`` (a starting worker
    registers only after its imports), so a single worker process runs at a time.
    """
    started = time.monotonic()
    last_seen_live = time.monotonic()
    last: tuple[object, ...] | None = None
    while True:
        prog = store.progress(job_id)
        if prog is None:
            raise KeyError(job_id)
        key = (prog.status, prog.stage, prog.done, prog.total, prog.current_item)
        if on_progress and key != last:
            on_progress(prog)
            last = key
        if prog.status in {s.value for s in JOB_TERMINAL}:
            return prog
        if control is not None:
            if live_worker(control) is not None:
                last_seen_live = time.monotonic()
            else:
                exited = worker is not None and worker.poll() is not None
                silent = time.monotonic() - last_seen_live > REGISTRATION_GRACE_S
                if exited or silent:
                    worker = start_worker()
                    last_seen_live = time.monotonic()
        if timeout_s is not None and time.monotonic() - started > timeout_s:
            raise TimeoutError(f"job {job_id} still {prog.status} after {timeout_s}s")
        time.sleep(poll_s)
