"""Run jobs to completion with an in-process worker (threads), for tests."""

from __future__ import annotations

import threading
import time

from mosaic.jobs.store import JobStore
from mosaic.jobs.worker import Worker
from mosaic.storage.control import ControlDB


def run_job(
    control: ControlDB, job_id: int, timeout: float = 600, slots: dict[str, int] | None = None
) -> str:
    store = JobStore(control.db)
    worker = Worker(control, slots=slots or {"cpu": 4, "io": 2, "gpu_encode": 2, "ai_api": 2})
    th = threading.Thread(target=worker.run, daemon=True)
    th.start()
    deadline = time.monotonic() + timeout
    status = "timeout"
    try:
        while time.monotonic() < deadline:
            job = store.job(job_id)
            if job is not None and job.status in ("done", "failed", "cancelled"):
                status = job.status
                break
            time.sleep(0.05)
    finally:
        worker.stop.set()
        th.join(timeout=30)
    return status
