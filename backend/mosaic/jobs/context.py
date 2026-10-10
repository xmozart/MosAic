"""What a task handler sees while it runs."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from mosaic.jobs.executor import Executor
from mosaic.jobs.model import LeasedTask, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import Project


class TaskCancelledError(Exception):
    pass


class NoProject:
    """``ctx.project`` of an app-level task (ADR 0058): it has none, and saying so beats an
    AttributeError on ``None``."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"an app-level task has no project (asked for {name!r})")


@dataclass
class TaskContext:
    task: LeasedTask
    worker_id: str
    executor: Executor
    store: JobStore
    project: Project
    cancelled: threading.Event = field(default_factory=threading.Event)
    control: ControlDB | None = None
    _reported: float = field(default=0.0, repr=False)

    @property
    def params(self) -> dict[str, Any]:
        return self.task.params

    @contextmanager
    def write(self) -> Iterator[Session]:
        """Project DB writes are serialized per project (ARCHITECTURE.md §7)."""
        with self.project.write() as s:
            yield s

    def spawn(self, tasks: Sequence[TaskSpec]) -> list[int]:
        """Add tasks to this task's job (dynamic fan-out, e.g. one per asset)."""
        return self.executor.spawn(self.task.job_id, tasks)

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise TaskCancelledError(f"task {self.task.id} cancelled")

    def set_stage(self, stage: str) -> None:
        self.store.set_stage(self.task.job_id, stage)

    def report(self, done: int, total: int) -> None:
        """This task's own progress (e.g. bytes), shown as the job's percentage. Writes at
        most every half second, plus the final value."""
        now = time.monotonic()
        if done < total and now - self._reported < 0.5:
            return
        self._reported = now
        self.store.set_job_result(self.task.job_id, {"progress": {"done": done, "total": total}})
