"""Control DB (app-level) ORM models. Alembic tree: storage/migrations/control."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ControlBase(DeclarativeBase):
    pass


class Installation(ControlBase):
    __tablename__ = "installation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(26), unique=True)
    created_at: Mapped[str] = mapped_column(String(40))


class User(ControlBase):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[str] = mapped_column(String(40))


class ProjectRegistry(ControlBase):
    __tablename__ = "project_registry"
    project_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    name: Mapped[str] = mapped_column(Text)
    root_path: Mapped[str] = mapped_column(Text)
    placement: Mapped[str] = mapped_column(String(20))
    fs_class: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[str] = mapped_column(String(40))
    last_opened_at: Mapped[str] = mapped_column(String(40))


class EditIndex(ControlBase):
    """edit_id → project, so ``/edits/{eid}`` routes resolve (ARCHITECTURE.md §5.1)."""

    __tablename__ = "edit_index"
    edit_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project_registry.project_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))


# ----------------------------------------------------------------------------- job DAG
# ARCHITECTURE.md §7. Lease expiry and heartbeats are integer epoch milliseconds.


class Job(ControlBase):
    __tablename__ = "job"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    project_id: Mapped[str] = mapped_column(String(26), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), index=True)
    stage: Mapped[str | None] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_limit_usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    first_done_ms: Mapped[int | None] = mapped_column(BigInteger)


class Task(ControlBase):
    __tablename__ = "task"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(26))
    kind: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(64))
    resource_class: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_keys: Mapped[list[Any]] = mapped_column(JSON, default=list)
    output_key: Mapped[str | None] = mapped_column(String(160))
    label: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (Index("ix_task_lease", "status", "resource_class", "priority"),)


class TaskDependency(ControlBase):
    __tablename__ = "task_dependency"
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), primary_key=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("task.id"), primary_key=True, index=True)


class Lease(ControlBase):
    __tablename__ = "lease"
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(64))
    expires_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    heartbeat_ms: Mapped[int] = mapped_column(BigInteger)


class TaskEvent(ControlBase):
    """Append-only task log: leased, started, skipped_existing, done, failed, requeued..."""

    __tablename__ = "task_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), index=True)
    event: Mapped[str] = mapped_column(String(24))
    worker_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class WorkerRecord(ControlBase):
    """Live worker processes (one in M0), for the CLI to find or start one."""

    __tablename__ = "worker"
    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    host: Mapped[str] = mapped_column(String(255))
    heartbeat_ms: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[str] = mapped_column(String(40))
