"""Keeps a worker running while the server has work (ADR 0056).

HTTP handlers only create, query or cancel jobs (invariant 8); something must run them.
The CLI starts a worker for the job it follows (`jobs.client.ensure_worker`); the server
runs this loop instead: whenever a job is pending or running and no live worker is
registered, it starts one. Workers exit after a short idle time, so an idle server holds
no worker. This also resumes work left unfinished when the server last stopped.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

from sqlalchemy import func, select

from mosaic.jobs.client import REGISTRATION_GRACE_S, live_worker, start_worker
from mosaic.jobs.model import JobStatus
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import Job

log = logging.getLogger(__name__)

POLL_S = 1.0
QUICK_EXIT_S = 10.0  # a worker gone sooner than this failed to start
MIN_BACKOFF_S = 2.0
MAX_BACKOFF_S = 60.0
RUNNABLE = (JobStatus.PENDING.value, JobStatus.RUNNING.value)


def has_work(control: ControlDB) -> bool:
    """A job a worker would run now (paused jobs wait for the user)."""
    with control.db.session() as s:
        return bool(s.scalar(select(func.count()).where(Job.status.in_(RUNNABLE))))


class WorkerSupervisor:
    def __init__(self, control: ControlDB, poll_s: float = POLL_S) -> None:
        self.control = control
        self.poll_s = poll_s
        self.stop = threading.Event()
        self._proc: subprocess.Popen[bytes] | None = None
        self._started_at = 0.0
        self._next_start = 0.0  # monotonic time before which no worker starts
        self._backoff = 0.0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="worker-supervisor")
        self._thread.start()

    def shutdown(self) -> None:
        """Stops supervising. A running worker finishes its tasks and exits when idle."""
        self.stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def tick(self) -> bool:
        """One check; True when it started a worker."""
        now = time.monotonic()
        if self._proc is not None and self._proc.poll() is not None:
            # A worker that dies right after starting (a broken install, an unwritable
            # /data) is retried later and later, not every second.
            if now - self._started_at < QUICK_EXIT_S:
                self._backoff = min(MAX_BACKOFF_S, max(2 * self._backoff, MIN_BACKOFF_S))
                log.warning("the job worker exited at once; next try in %.0f s", self._backoff)
            else:
                self._backoff = 0.0
            self._next_start = now + self._backoff
            self._proc = None
        if not has_work(self.control) or live_worker(self.control) is not None:
            return False
        if self._proc is not None:
            if now - self._started_at < REGISTRATION_GRACE_S:
                return False  # it registers only after its imports
            log.warning("the job worker (pid %s) never registered; replacing it", self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
            self._backoff = min(MAX_BACKOFF_S, max(2 * self._backoff, MIN_BACKOFF_S))
            self._next_start = now + self._backoff
        if now < self._next_start:
            return False
        self._proc = start_worker()
        self._started_at = now
        log.info("started a job worker (pid %s)", self._proc.pid)
        return True

    def _loop(self) -> None:
        while not self.stop.wait(self.poll_s):
            try:
                self.tick()
            except Exception:  # never let the server lose its supervisor
                log.exception("worker supervisor check failed")
