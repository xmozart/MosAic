"""``Executor``: the only way work is dispatched (ARCHITECTURE.md §7, FUTURE_APPENDIX §3).

Workers lease and report through it, and the API controls jobs through it, so a
distributed executor can replace ``LocalExecutor`` without schema changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from mosaic.core.principal import Principal, check
from mosaic.jobs.model import JobSpec, LeasedTask, TaskSpec
from mosaic.jobs.store import JobStore


class Executor(Protocol):
    def submit(self, principal: Principal, job: JobSpec) -> int: ...
    def spawn(self, job_id: int, tasks: Sequence[TaskSpec]) -> list[int]: ...
    def cancel(self, principal: Principal, job_id: int) -> None: ...
    def pause(self, principal: Principal, job_id: int) -> None: ...
    def resume(self, principal: Principal, job_id: int) -> None: ...
    def retry_failed(self, principal: Principal, job_id: int) -> int: ...
    def lease(self, worker_id: str, resource_class: str) -> LeasedTask | None: ...
    def heartbeat(self, task_id: int, worker_id: str) -> bool: ...
    def complete(
        self,
        task_id: int,
        worker_id: str,
        *,
        skipped_existing: bool = False,
        result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool: ...
    def skip(self, task_id: int, worker_id: str, reason: str) -> bool: ...
    def fail(self, task_id: int, worker_id: str, error: str, *, retryable: bool) -> bool: ...
    def defer(self, task_id: int, worker_id: str, reason: str) -> bool: ...


class LocalExecutor:
    """DB-backed queue consumed by local worker processes."""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    def submit(self, principal: Principal, job: JobSpec) -> int:
        check(principal, "job.submit", job.project_id)
        return self.store.create_job(principal, job)

    def spawn(self, job_id: int, tasks: Sequence[TaskSpec]) -> list[int]:
        return self.store.add_tasks(job_id, tasks)

    def cancel(self, principal: Principal, job_id: int) -> None:
        check(principal, "job.cancel", str(job_id))
        self.store.cancel(job_id)

    def pause(self, principal: Principal, job_id: int) -> None:
        check(principal, "job.pause", str(job_id))
        self.store.pause(job_id)

    def resume(self, principal: Principal, job_id: int) -> None:
        check(principal, "job.resume", str(job_id))
        self.store.resume(job_id)

    def retry_failed(self, principal: Principal, job_id: int) -> int:
        check(principal, "job.retry", str(job_id))
        return self.store.retry_failed(job_id)

    def lease(self, worker_id: str, resource_class: str) -> LeasedTask | None:
        return self.store.lease(worker_id, resource_class)

    def heartbeat(self, task_id: int, worker_id: str) -> bool:
        return self.store.heartbeat(task_id, worker_id)

    def complete(
        self,
        task_id: int,
        worker_id: str,
        *,
        skipped_existing: bool = False,
        result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        return self.store.complete(
            task_id,
            worker_id,
            skipped_existing=skipped_existing,
            result=result,
            duration_ms=duration_ms,
        )

    def skip(self, task_id: int, worker_id: str, reason: str) -> bool:
        return self.store.skip(task_id, worker_id, reason)

    def fail(self, task_id: int, worker_id: str, error: str, *, retryable: bool) -> bool:
        return self.store.fail(task_id, worker_id, error, retryable=retryable)

    def defer(self, task_id: int, worker_id: str, reason: str) -> bool:
        return self.store.defer(task_id, worker_id, reason)
