"""What a task handler sees while it runs."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from mosaic.jobs.executor import Executor
from mosaic.jobs.model import LeasedTask, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.storage.projects import Project


class TaskCancelledError(Exception):
    pass


@dataclass
class TaskContext:
    task: LeasedTask
    worker_id: str
    executor: Executor
    store: JobStore
    project: Project
    cancelled: threading.Event = field(default_factory=threading.Event)

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
