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
from mosaic.media import hardware
from mosaic.storage import lease
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import Job, TaskEvent, WorkerRecord
from mosaic.storage.projects import Project, open_project

log = logging.getLogger("mosaic.worker")

ENV_LEASE_MS = "MOSAIC_LEASE_MS"


GB = 1 << 30
SLOT_MEMORY = 2 * GB  # a heavy CPU task (Whisper medium, the frame pass) at its peak
SLOT_SETTINGS = {rc.value: f"workers.{rc.value}" for rc in ResourceClass}


def default_slots(
    hw: hardware.Hardware | None = None, overrides: dict[str, int] | None = None
) -> dict[str, int]:
    """Slots per resource class, sized from the hardware probe (ARCHITECTURE.md §3,
    ADR 0030); a positive override (the ``workers.<class>`` settings) wins."""
    hw = hw or hardware.probe()
    cpu = max(2, hw.cpu_logical // 2)
    if hw.memory_bytes:
        cpu = max(1, min(cpu, hw.memory_bytes // SLOT_MEMORY))
    slots = {
        ResourceClass.CPU.value: cpu,
        # A hardware encoder runs two sessions well; software encoding is CPU work.
        ResourceClass.GPU_ENCODE.value: 2 if hw.hw_encoders else 1,
        # Concurrency per provider is limited separately (ai/ratelimit.py).
        ResourceClass.AI_API.value: 4,
        ResourceClass.IO.value: 2,
    }
    for rc, n in (overrides or {}).items():
        if n > 0:
            slots[rc] = n
    return slots


def configured_slots(control: ControlDB) -> dict[str, int]:
    from mosaic.storage.config import ConfigService

    config = ConfigService(control)
    me = control.local_principal
    return default_slots(
        overrides={rc: int(config.get(me, key)) for rc, key in SLOT_SETTINGS.items()}
    )


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
                try:
                    self._projects[project_id] = open_project(
                        self.control, self.control.local_principal, Path(root)
                    )
                except lease.LeaseHeldError as exc:
                    raise registry.PermanentError(str(exc)) from None
            project = self._projects[project_id]
        # Renew the project's lease while working on it (a cheap no-op when recent). If
        # another computer took it over, stop writing to the project.
        try:
            lease.acquire(project.outputs_dir, self.control.installation_id)
        except lease.LeaseHeldError as exc:
            with self._projects_lock:
                self._projects.pop(project_id, None)
            project.close(checkpoint=False)
            raise registry.PermanentError(str(exc)) from None
        return project

    def _release_idle_projects(self) -> None:
        """Close cached projects that have no unfinished job: an idle worker never keeps a
        project open, so it can be moved or removed (ADR 0051)."""
        with self._projects_lock:
            idle = [pid for pid in self._projects if not self.store.jobs(pid, True, limit=1)]
            closing = [self._projects.pop(pid) for pid in idle]
        for p in closing:
            p.close()

    def _checkpoint(self, project: Project) -> None:
        try:
            project.checkpoint()
        except Exception:
            log.exception("snapshot of project %s failed; the live DB is unaffected", project.id)
        try:
            from mosaic.storage import project_cards

            project_cards.refresh(self.control, project)  # the Home card (S3)
        except Exception:
            log.exception("updating the card of project %s failed", project.id)

    # ---------------------------------------------------------------- execution

    def _heartbeat_loop(
        self, task: LeasedTask, cancelled: threading.Event, done: threading.Event
    ) -> None:
        interval = max(self.lease_ms / 4000, 0.05)
        renewed = time.monotonic()
        while not done.wait(interval):
            if not self.executor.heartbeat(task.id, self.worker_id):
                cancelled.set()
                return
            if time.monotonic() - renewed >= lease.RENEW_AFTER_S:
                # Long tasks keep the project lease alive; a takeover stops the task, so
                # it does not keep writing to a project another computer now edits.
                renewed = time.monotonic()
                project = self._projects.get(task.project_id)
                if project is None:
                    continue
                try:
                    lease.acquire(project.outputs_dir, self.control.installation_id)
                except lease.LeaseHeldError:
                    log.warning(
                        "project %s was taken over; cancelling task %s", task.project_id, task.id
                    )
                    cancelled.set()
                    return
                except OSError:
                    pass  # an offline share: try again next round

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
            ctx = TaskContext(
                task,
                self.worker_id,
                self.executor,
                self.store,
                project,
                cancelled,
                control=self.control,
            )
            if handler.is_done is not None and handler.is_done(ctx):
                self.executor.complete(task.id, self.worker_id, skipped_existing=True)
                return
            self._log_event(task.id, "started")
            result = handler.run(ctx)
            ms = int((time.monotonic() - started) * 1000)
            self.executor.complete(task.id, self.worker_id, result=result or {}, duration_ms=ms)
            if handler.checkpoint:
                # A stage finished (analysis stage, edit commit, render): snapshot a split
                # project's DB into its folder (§4). Never affects the task's outcome.
                self._checkpoint(project)
        except registry.DeferTask as exc:
            self.executor.defer(task.id, self.worker_id, str(exc))
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
                if not self._busy:
                    self._release_idle_projects()
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
    control = ControlDB()
    worker = Worker(control, slots=configured_slots(control), lease_ms=lease_ms)
    log.info("worker slots: %s", worker.slots)
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    worker.run(exit_when_idle_s=args.exit_when_idle)


if __name__ == "__main__":
    main()
