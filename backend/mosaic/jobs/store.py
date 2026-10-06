"""Job DAG persistence: scheduling, atomic leases, heartbeats, expiry and progress.

Every statement is portable SQLAlchemy Core/ORM (``UPDATE … RETURNING`` is supported by
SQLite ≥ 3.35 and PostgreSQL), so the DAG store can move to another database later.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, delete, exists, func, select, update
from sqlalchemy.orm import Session, aliased

from mosaic.core.clock import now_iso
from mosaic.core.principal import Principal
from mosaic.jobs.model import (
    JOB_TERMINAL,
    SATISFIED,
    TERMINAL,
    JobProgress,
    JobSpec,
    JobStatus,
    LeasedTask,
    TaskSpec,
    TaskStatus,
)
from mosaic.storage.db import Database
from mosaic.storage.models_control import Job, Lease, Task, TaskDependency, TaskEvent

LEASE_MS = 60_000


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class JobStore:
    def __init__(self, db: Database, lease_ms: int = LEASE_MS) -> None:
        self.db = db
        self.lease_ms = lease_ms

    # ------------------------------------------------------------------ creation

    def create_job(self, principal: Principal, spec: JobSpec) -> int:
        with self.db.session() as s:
            now = now_iso()
            job = Job(
                user_id=principal.user_id,
                project_id=spec.project_id,
                kind=spec.kind,
                status=JobStatus.PENDING.value,
                params=spec.params,
                result={},
                cost_limit_usd=spec.cost_limit_usd,
                created_at=now,
                updated_at=now,
            )
            s.add(job)
            s.flush()
            self._add_tasks(s, job.id, spec.project_id, spec.tasks)
            self._promote(s, job.id)
            return job.id

    def add_tasks(self, job_id: int, specs: Sequence[TaskSpec]) -> list[int]:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            ids = self._add_tasks(s, job_id, job.project_id, specs)
            self._promote(s, job_id)
            return ids

    def _add_tasks(
        self, s: Session, job_id: int, project_id: str, specs: Sequence[TaskSpec]
    ) -> list[int]:
        ids: list[int] = []
        now = now_iso()
        for spec in specs:
            task = Task(
                job_id=job_id,
                project_id=project_id,
                kind=spec.kind,
                stage=spec.stage,
                resource_class=spec.resource_class.value,
                status=TaskStatus.PENDING.value,
                priority=spec.priority,
                params=spec.params,
                input_keys=spec.input_keys,
                output_key=spec.output_key,
                label=spec.label,
                max_attempts=spec.max_attempts,
                result={},
                created_at=now,
            )
            s.add(task)
            s.flush()
            ids.append(task.id)
        for spec, tid in zip(specs, ids, strict=True):
            for dep in spec.deps:
                dep_id = dep[1] if isinstance(dep, tuple) else ids[dep]
                s.add(TaskDependency(task_id=tid, depends_on_id=dep_id))
        s.flush()
        return ids

    # ----------------------------------------------------------------- scheduling

    def _promote(self, s: Session, job_id: int | None = None) -> None:
        """pending → ready when all dependencies are satisfied; pending → cancelled when a
        dependency failed or was cancelled."""
        dep_task = aliased(Task)
        unsatisfied = exists().where(
            TaskDependency.task_id == Task.id,
            dep_task.id == TaskDependency.depends_on_id,
            dep_task.status.notin_([x.value for x in SATISFIED]),
        )
        broken = exists().where(
            TaskDependency.task_id == Task.id,
            dep_task.id == TaskDependency.depends_on_id,
            dep_task.status.in_([TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]),
        )
        scope = [Task.status == TaskStatus.PENDING.value]
        if job_id is not None:
            scope.append(Task.job_id == job_id)
        while True:  # cancellations cascade down the DAG, one level per pass
            res = s.execute(
                update(Task)
                .where(*scope, broken)
                .values(
                    status=TaskStatus.CANCELLED.value,
                    error="dependency failed",
                    finished_at=now_iso(),
                )
            )
            if not res.rowcount:  # type: ignore[attr-defined]
                break
        s.execute(update(Task).where(*scope, ~unsatisfied).values(status=TaskStatus.READY.value))

    def lease(
        self, worker_id: str, resource_class: str, lease_ms: int | None = None
    ) -> LeasedTask | None:
        """Atomically lease one ready task of ``resource_class`` from a runnable job."""
        lease_ms = self.lease_ms if lease_ms is None else lease_ms
        with self.db.session() as s:
            runnable = select(Job.id).where(
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value])
            )
            candidate = (
                select(Task.id)
                .where(
                    Task.status == TaskStatus.READY.value,
                    Task.resource_class == resource_class,
                    Task.job_id.in_(runnable),
                )
                .order_by(Task.priority.desc(), Task.id)
                .limit(1)
                .scalar_subquery()
            )
            row = s.execute(
                update(Task)
                .where(Task.id == candidate, Task.status == TaskStatus.READY.value)
                .values(status=TaskStatus.LEASED.value, attempts=Task.attempts + 1)
                .returning(
                    Task.id,
                    Task.job_id,
                    Task.project_id,
                    Task.kind,
                    Task.stage,
                    Task.resource_class,
                    Task.params,
                    Task.input_keys,
                    Task.output_key,
                    Task.attempts,
                )
            ).first()
            if row is None:
                return None
            now = now_ms()
            s.merge(
                Lease(
                    task_id=row.id, worker_id=worker_id, expires_ms=now + lease_ms, heartbeat_ms=now
                )
            )
            self._event(s, row.id, "leased", worker_id)
            s.execute(
                update(Job)
                .where(Job.id == row.job_id, Job.status == JobStatus.PENDING.value)
                .values(status=JobStatus.RUNNING.value, updated_at=now_iso())
            )
            # The stage shown is the latest started task's; it may refine it (set_stage).
            s.execute(update(Job).where(Job.id == row.job_id).values(stage=row.stage))
            return LeasedTask(
                row.id,
                row.job_id,
                row.project_id,
                row.kind,
                row.stage,
                row.resource_class,
                dict(row.params),
                list(row.input_keys),
                row.output_key,
                row.attempts,
            )

    def heartbeat(self, task_id: int, worker_id: str, lease_ms: int | None = None) -> bool:
        """Extend the lease. False if the lease was lost or the task/job was cancelled."""
        lease_ms = self.lease_ms if lease_ms is None else lease_ms
        with self.db.session() as s:
            now = now_ms()
            res = s.execute(
                update(Lease)
                .where(Lease.task_id == task_id, Lease.worker_id == worker_id)
                .values(expires_ms=now + lease_ms, heartbeat_ms=now)
            )
            if not res.rowcount:  # type: ignore[attr-defined]
                return False
            status = s.scalar(select(Task.status).where(Task.id == task_id))
            return status == TaskStatus.LEASED.value

    def _finish(
        self,
        task_id: int,
        worker_id: str,
        status: TaskStatus,
        event: str,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        with self.db.session() as s:
            if not self._release(s, task_id, worker_id):
                return False  # lease expired and was re-queued: drop the result
            res = s.execute(
                update(Task)
                .where(Task.id == task_id, Task.status == TaskStatus.LEASED.value)
                .values(
                    status=status.value,
                    error=error,
                    result=result or {},
                    finished_at=now_iso(),
                    duration_ms=duration_ms,
                )
            )
            if not res.rowcount:  # type: ignore[attr-defined]
                return False  # task was cancelled while running
            self._event(s, task_id, event, worker_id, error)
            job_id = s.scalar(select(Task.job_id).where(Task.id == task_id))
            assert job_id is not None
            if status in SATISFIED:
                s.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.first_done_ms.is_(None))
                    .values(first_done_ms=now_ms())
                )
            self._promote(s, job_id)
            self._settle_job(s, job_id)
            return True

    @staticmethod
    def _release(s: Session, task_id: int, worker_id: str) -> bool:
        """Atomically drop the lease iff ``worker_id`` still holds it."""
        res = s.execute(delete(Lease).where(Lease.task_id == task_id, Lease.worker_id == worker_id))
        return bool(res.rowcount)  # type: ignore[attr-defined]

    def complete(
        self,
        task_id: int,
        worker_id: str,
        *,
        skipped_existing: bool = False,
        result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        event = "skipped_existing" if skipped_existing else "done"
        return self._finish(
            task_id, worker_id, TaskStatus.DONE, event, result=result, duration_ms=duration_ms
        )

    def skip(self, task_id: int, worker_id: str, reason: str) -> bool:
        """Handler decided the task does not apply (e.g. no audio stream)."""
        return self._finish(task_id, worker_id, TaskStatus.SKIPPED, "skipped", error=reason)

    def fail(self, task_id: int, worker_id: str, error: str, *, retryable: bool) -> bool:
        if retryable:
            with self.db.session() as s:
                task = s.get(Task, task_id)
                if task is None or task.attempts >= task.max_attempts:
                    pass
                else:
                    if not self._release(s, task_id, worker_id):
                        return False  # someone else owns the task now
                    res = s.execute(
                        update(Task)
                        .where(Task.id == task_id, Task.status == TaskStatus.LEASED.value)
                        .values(status=TaskStatus.READY.value, error=error)
                    )
                    if res.rowcount:  # type: ignore[attr-defined]
                        self._event(s, task_id, "retry", worker_id, error)
                    return True
        return self._finish(task_id, worker_id, TaskStatus.FAILED, "failed", error=error)

    def requeue_expired(self) -> int:
        """Expired leases (crashed or hung workers) return their tasks to ready."""
        with self.db.session() as s:
            now = now_ms()
            expired = list(s.scalars(select(Lease.task_id).where(Lease.expires_ms < now)))
            requeued = 0
            for tid in expired:
                res = s.execute(delete(Lease).where(Lease.task_id == tid, Lease.expires_ms < now))
                if not res.rowcount:  # type: ignore[attr-defined]
                    continue  # a heartbeat renewed it in the meantime
                requeued += 1
                task = s.get(Task, tid)
                if task is None or task.status != TaskStatus.LEASED.value:
                    continue
                if task.attempts >= task.max_attempts:
                    task.status = TaskStatus.FAILED.value
                    task.error = "lease expired too many times"
                    self._event(s, tid, "failed", None, task.error)
                    self._promote(s, task.job_id)
                    self._settle_job(s, task.job_id)
                else:
                    task.status = TaskStatus.READY.value
                    self._event(s, tid, "requeued", None, "lease expired")
            return requeued

    def promote_all(self) -> None:
        with self.db.session() as s:
            self._promote(s)
            active = s.scalars(
                select(Job.id).where(Job.status.notin_([x.value for x in JOB_TERMINAL]))
            )
            for job_id in list(active):
                self._settle_job(s, job_id)

    # ------------------------------------------------------------------ job control

    def _settle_job(self, s: Session, job_id: int) -> None:
        job = s.get(Job, job_id)
        if job is None or job.status in {x.value for x in JOB_TERMINAL}:
            return
        open_count = s.scalar(
            select(func.count()).where(
                Task.job_id == job_id, Task.status.notin_([x.value for x in TERMINAL])
            )
        )
        if open_count:
            return
        failed = s.scalar(
            select(func.count()).where(
                Task.job_id == job_id, Task.status == TaskStatus.FAILED.value
            )
        )
        job.status = (JobStatus.FAILED if failed else JobStatus.DONE).value
        job.updated_at = now_iso()

    def cancel(self, job_id: int) -> None:
        with self.db.session() as s:
            now = now_iso()
            s.execute(
                update(Task)
                .where(Task.job_id == job_id, Task.status.notin_([x.value for x in TERMINAL]))
                .values(status=TaskStatus.CANCELLED.value, finished_at=now, error="cancelled")
            )
            s.execute(
                update(Job)
                .where(Job.id == job_id, Job.status.notin_([x.value for x in JOB_TERMINAL]))
                .values(status=JobStatus.CANCELLED.value, updated_at=now)
            )

    def pause(self, job_id: int, *, cost_limit: bool = False) -> None:
        status = JobStatus.PAUSED_COST_LIMIT if cost_limit else JobStatus.PAUSED
        with self.db.session() as s:
            s.execute(
                update(Job)
                .where(Job.id == job_id, Job.status.notin_([x.value for x in JOB_TERMINAL]))
                .values(status=status.value, updated_at=now_iso())
            )

    def set_cost_limit(self, job_id: int, usd: float) -> None:
        """Raise (or set) a job's AI cost limit, e.g. before resuming a cost-limit pause."""
        with self.db.session() as s:
            s.execute(
                update(Job).where(Job.id == job_id).values(cost_limit_usd=usd, updated_at=now_iso())
            )

    def resume(self, job_id: int) -> None:
        with self.db.session() as s:
            s.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status.in_([JobStatus.PAUSED.value, JobStatus.PAUSED_COST_LIMIT.value]),
                )
                .values(status=JobStatus.RUNNING.value, updated_at=now_iso())
            )

    def retry_failed(self, job_id: int) -> int:
        with self.db.session() as s:
            res = s.execute(
                update(Task)
                .where(
                    Task.job_id == job_id,
                    Task.status.in_([TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]),
                )
                .values(status=TaskStatus.PENDING.value, attempts=0, error=None)
            )
            reset = int(res.rowcount)  # type: ignore[attr-defined]
            if not reset:
                return 0
            s.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status=JobStatus.RUNNING.value, updated_at=now_iso())
            )
            self._promote(s, job_id)
            self._settle_job(s, job_id)
            return reset

    def set_stage(self, job_id: int, stage: str) -> None:
        with self.db.session() as s:
            s.execute(update(Job).where(Job.id == job_id).values(stage=stage, updated_at=now_iso()))

    def add_cost(self, job_id: int, usd: float) -> float:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return 0.0
            job.cost_usd = (job.cost_usd or 0.0) + usd
            return job.cost_usd

    def reserve_cost(self, job_id: int, usd: float) -> bool:
        """Atomically add ``usd`` to the job's spend if it stays within the job's cost
        limit (no limit: always). False means the budget would be exceeded."""
        with self.db.session() as s:
            limit = Job.cost_limit_usd
            res = s.execute(
                update(Job)
                .where(Job.id == job_id, (limit.is_(None)) | (Job.cost_usd + usd <= limit))
                .values(cost_usd=Job.cost_usd + usd, updated_at=now_iso())
            )
            return bool(res.rowcount)  # type: ignore[attr-defined]

    def adjust_cost(self, job_id: int, delta_usd: float) -> None:
        """Replace a reservation by the actual cost (``delta`` = actual − reserved)."""
        with self.db.session() as s:
            s.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(cost_usd=Job.cost_usd + delta_usd, updated_at=now_iso())
            )

    def defer(self, task_id: int, worker_id: str, reason: str) -> bool:
        """Put a leased task back to ready without counting the attempt (e.g. its job was
        paused at the cost limit)."""
        with self.db.session() as s:
            if not self._release(s, task_id, worker_id):
                return False
            res = s.execute(
                update(Task)
                .where(Task.id == task_id, Task.status == TaskStatus.LEASED.value)
                .values(status=TaskStatus.READY.value, attempts=Task.attempts - 1)
            )
            if res.rowcount:  # type: ignore[attr-defined]
                self._event(s, task_id, "deferred", worker_id, reason)
            return True

    def set_job_result(self, job_id: int, result: dict[str, Any]) -> None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is not None:
                job.result = {**(job.result or {}), **result}

    # -------------------------------------------------------------------- queries

    def job(self, job_id: int) -> Job | None:
        with self.db.session() as s:
            return s.get(Job, job_id)

    def task(self, task_id: int) -> Task | None:
        with self.db.session() as s:
            return s.get(Task, task_id)

    def tasks(self, job_id: int, status: str | None = None) -> list[Task]:
        with self.db.session() as s:
            q = select(Task).where(Task.job_id == job_id)
            if status:
                q = q.where(Task.status == status)
            return list(s.scalars(q.order_by(Task.id)))

    def events(self, job_id: int) -> list[TaskEvent]:
        with self.db.session() as s:
            q = (
                select(TaskEvent)
                .join(Task, Task.id == TaskEvent.task_id)
                .where(Task.job_id == job_id)
                .order_by(TaskEvent.id)
            )
            return list(s.scalars(q))

    def jobs(
        self,
        project_id: str | None = None,
        active: bool | None = None,
        *,
        kind: str | None = None,
        cursor: int | None = None,
        limit: int = 200,
    ) -> list[Job]:
        """Newest first. ``cursor`` is the last job id of the previous page."""
        with self.db.session() as s:
            q = select(Job)
            if project_id:
                q = q.where(Job.project_id == project_id)
            if kind:
                q = q.where(Job.kind == kind)
            if active is True:
                q = q.where(Job.status.notin_([x.value for x in JOB_TERMINAL]))
            if cursor is not None:
                q = q.where(Job.id < cursor)
            return list(s.scalars(q.order_by(Job.id.desc()).limit(limit)))

    def edit_jobs(self, project_id: str, edit_ids: list[int], active: bool) -> dict[int, Job]:
        """The newest edit job of each of these edits (``active``: unfinished ones only)."""
        eid = Job.params["edit_id"].as_integer()
        q = select(Job).where(Job.project_id == project_id, Job.kind == "edit", eid.in_(edit_ids))
        if active:
            q = q.where(Job.status.notin_([x.value for x in JOB_TERMINAL]))
        out: dict[int, Job] = {}
        with self.db.session() as s:
            for j in s.scalars(q.order_by(Job.id.desc())):
                out.setdefault(int(j.params["edit_id"]), j)
        return out

    def stage_counts(self, job_id: int) -> dict[str, dict[str, int]]:
        with self.db.session() as s:
            rows = s.execute(
                select(Task.stage, Task.status, func.count())
                .where(Task.job_id == job_id)
                .group_by(Task.stage, Task.status)
            ).all()
        out: dict[str, dict[str, int]] = {}
        for stage, status, n in rows:
            st = out.setdefault(stage, {"total": 0, "done": 0, "failed": 0})
            st["total"] += n
            if status in (TaskStatus.DONE.value, TaskStatus.SKIPPED.value):
                st["done"] += n
            elif status == TaskStatus.FAILED.value:
                st["failed"] += n
        return out

    def progress(self, job_id: int) -> JobProgress | None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return None
            rows = s.execute(
                select(Task.status, func.count()).where(Task.job_id == job_id).group_by(Task.status)
            ).all()
            counts: dict[str, int] = {status: n for status, n in rows}
            total = sum(counts.values())
            done = sum(counts.get(x.value, 0) for x in TERMINAL)
            current = s.scalar(
                select(Task.label)
                .join(Lease, Lease.task_id == Task.id)
                .where(Task.job_id == job_id)
                .limit(1)
            )
            eta = None
            if total and done * 10 >= total and job.first_done_ms and done < total:
                elapsed = now_ms() - job.first_done_ms
                eta = int(elapsed * (total - done) / max(done, 1))
            return JobProgress(
                job.id,
                job.project_id,
                job.kind,
                job.status,
                job.stage,
                done,
                total,
                counts.get(TaskStatus.FAILED.value, 0),
                current,
                job.cost_usd or 0.0,
                eta,
            )

    def has_ready(self, resource_class: str) -> bool:
        with self.db.session() as s:
            return bool(
                s.scalar(
                    select(func.count()).where(
                        and_(
                            Task.status == TaskStatus.READY.value,
                            Task.resource_class == resource_class,
                        )
                    )
                )
            )

    def _event(
        self, s: Session, task_id: int, event: str, worker_id: str | None, detail: str | None = None
    ) -> None:
        s.add(
            TaskEvent(
                task_id=task_id,
                event=event,
                worker_id=worker_id,
                detail=detail,
                created_at=now_iso(),
            )
        )
