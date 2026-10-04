"""Worker process: one process, a thread per resource-class slot (ADR 0002 K).

Run with ``python -m mosaic.jobs.worker``. All work arrives through ``Executor.lease``.
Workers are stateless between tasks: everything a task needs comes from its row, the
project DB and the artifact store.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.jobs import registry
from mosaic.jobs.context import TaskCancelledError, TaskContext
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.model import JOB_TERMINAL, LeasedTask, ResourceClass
from mosaic.jobs.store import LEASE_MS, JobStore, now_ms
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import Job, TaskEvent, WorkerRecord
from mosaic.storage.projects import Project, open_project

log = logging.getLogger("mosaic.worker")

ENV_LEASE_MS = "MOSAIC_LEASE_MS"


def default_slots() -> dict[str, int]:
    cpus = os.cpu_count() or 4
    return {
        ResourceClass.CPU.value: max(2, cpus // 2),
        ResourceClass.GPU_ENCODE.value: 2,
        ResourceClass.AI_API.value: 4,
        ResourceClass.IO.value: 2,
    }


@dataclass
class Worker:
    control: ControlDB
    slots: dict[str, int] = field(default_factory=default_slots)
    lease_ms: int = LEASE_MS
    poll_s: float = 0.2
    worker_id: str = field(
        default_factory=lambda: f"{socket.gethostname()}:{os.getpid()}:{new_ulid()[-6:]}"
    )

    def __post_init__(self) -> None:
        self.store = JobStore(self.control.db, self.lease_ms)
        self.executor = LocalExecutor(self.store)
        self.stop = threading.Event()
        self._projects: dict[str, Project] = {}
        self._projects_lock = threading.Lock()
        self._busy = 0
        self._busy_lock = threading.Lock()

    # ----------------------------------------------------------------- projects

    def _project(self, project_id: str) -> Project:
        with self._projects_lock:
            if project_id not in self._projects:
                root = self.control.project_root(project_id)
                if root is None:
                    raise registry.PermanentError(f"unknown project {project_id}")
                self._projects[project_id] = open_project(
                    self.control, self.control.local_principal, Path(root)
                )
            return self._projects[project_id]

    # ---------------------------------------------------------------- execution

    def _heartbeat_loop(
        self, task: LeasedTask, cancelled: threading.Event, done: threading.Event
    ) -> None:
        interval = max(self.lease_ms / 4000, 0.05)
        while not done.wait(interval):
            if not self.executor.heartbeat(task.id, self.worker_id):
                cancelled.set()
                return

    def _log_event(self, task_id: int, event: str) -> None:
        with self.control.db.session() as s:
            s.add(
                TaskEvent(
                    task_id=task_id, event=event, worker_id=self.worker_id, created_at=now_iso()
                )
            )

    def execute(self, task: LeasedTask) -> None:
        started = time.monotonic()
        done = threading.Event()
        cancelled = threading.Event()
        hb = threading.Thread(
            target=self._heartbeat_loop, args=(task, cancelled, done), daemon=True
        )
        hb.start()
        try:
            handler = registry.get(task.kind)
            project = self._project(task.project_id)
            ctx = TaskContext(task, self.worker_id, self.executor, self.store, project, cancelled)
            if handler.is_done is not None and handler.is_done(ctx):
                self.executor.complete(task.id, self.worker_id, skipped_existing=True)
                return
            self._log_event(task.id, "started")
            result = handler.run(ctx)
            ms = int((time.monotonic() - started) * 1000)
            self.executor.complete(task.id, self.worker_id, result=result or {}, duration_ms=ms)
        except registry.SkipTask as exc:
            self.executor.skip(task.id, self.worker_id, str(exc))
        except TaskCancelledError:
            log.info("task %s cancelled", task.id)
        except registry.PermanentError as exc:
            self.executor.fail(task.id, self.worker_id, str(exc), retryable=False)
        except Exception as exc:
            log.exception("task %s failed", task.id)
            detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=8)}"
            self.executor.fail(task.id, self.worker_id, detail[-4000:], retryable=True)
        finally:
            done.set()
            hb.join(timeout=5)

    def _slot_loop(self, resource_class: str) -> None:
        while not self.stop.is_set():
            try:
                task = self.executor.lease(self.worker_id, resource_class)
            except Exception:
                log.exception("lease failed")
                task = None
            if task is None:
                self.stop.wait(self.poll_s)
                continue
            with self._busy_lock:
                self._busy += 1
            try:
                self.execute(task)
            finally:
                with self._busy_lock:
                    self._busy -= 1

    # --------------------------------------------------------------- lifecycle

    def _register(self) -> None:
        with self.control.db.session() as s:
            s.merge(
                WorkerRecord(
                    worker_id=self.worker_id,
                    pid=os.getpid(),
                    host=socket.gethostname(),
                    heartbeat_ms=now_ms(),
                    started_at=now_iso(),
                )
            )

    def _unregister(self) -> None:
        with self.control.db.session() as s:
            s.execute(delete(WorkerRecord).where(WorkerRecord.worker_id == self.worker_id))

    def _active_jobs(self) -> int:
        with self.control.db.session() as s:
            from sqlalchemy import func, select

            return int(
                s.scalar(
                    select(func.count()).where(Job.status.notin_([x.value for x in JOB_TERMINAL]))
                )
                or 0
            )

    def run(self, exit_when_idle_s: float | None = None) -> None:
        registry.load_handlers()
        self._register()
        threads = [
            threading.Thread(target=self._slot_loop, args=(rc,), daemon=True, name=f"slot-{rc}-{i}")
            for rc, n in self.slots.items()
            for i in range(n)
        ]
        for t in threads:
            t.start()
        idle_since = time.monotonic()
        try:
            while not self.stop.wait(0.5):
                self.store.requeue_expired()
                self.store.promote_all()
                with self.control.db.session() as s:
                    rec = s.get(WorkerRecord, self.worker_id)
                    if rec is not None:
                        rec.heartbeat_ms = now_ms()
                if exit_when_idle_s is not None:
                    if self._busy or self._active_jobs():
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since > exit_when_idle_s:
                        break
        finally:
            self.stop.set()
            for t in threads:
                t.join(timeout=10)
            self._unregister()
            for p in self._projects.values():
                p.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mosaic-worker")
    parser.add_argument(
        "--exit-when-idle",
        type=float,
        default=None,
        help="exit after this many seconds with no active jobs",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lease_ms = int(os.environ.get(ENV_LEASE_MS, LEASE_MS))
    worker = Worker(ControlDB(), lease_ms=lease_ms)
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    worker.run(exit_when_idle_s=args.exit_when_idle)


if __name__ == "__main__":
    main()
