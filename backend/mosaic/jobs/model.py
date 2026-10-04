"""Job and task vocabulary (ARCHITECTURE.md §7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    LEASED = "leased"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED})
SATISFIED = frozenset({TaskStatus.DONE, TaskStatus.SKIPPED})


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    PAUSED_COST_LIMIT = "paused_cost_limit"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


JOB_TERMINAL = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})


class ResourceClass(StrEnum):
    CPU = "cpu"
    GPU_ENCODE = "gpu_encode"
    AI_API = "ai_api"
    IO = "io"


@dataclass
class TaskSpec:
    """A task to create. ``deps`` are indexes into the same submission or existing ids
    (``("id", 12)``)."""

    kind: str
    stage: str
    resource_class: ResourceClass = ResourceClass.CPU
    params: dict[str, Any] = field(default_factory=dict)
    input_keys: list[str] = field(default_factory=list)
    output_key: str | None = None
    label: str | None = None
    priority: int = 0
    deps: list[int | tuple[str, int]] = field(default_factory=list)
    max_attempts: int = 3


@dataclass
class JobSpec:
    project_id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    tasks: list[TaskSpec] = field(default_factory=list)
    cost_limit_usd: float | None = None


@dataclass(frozen=True)
class LeasedTask:
    id: int
    job_id: int
    project_id: str
    kind: str
    stage: str
    resource_class: str
    params: dict[str, Any]
    input_keys: list[str]
    output_key: str | None
    attempts: int


@dataclass(frozen=True)
class JobProgress:
    job_id: int
    project_id: str
    kind: str
    status: str
    stage: str | None
    done: int
    total: int
    failed: int
    current_item: str | None
    cost_usd: float
    eta_ms: int | None

    @property
    def pct(self) -> int:
        return 100 * self.done // self.total if self.total else 0
