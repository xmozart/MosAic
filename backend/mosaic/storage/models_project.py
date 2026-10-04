"""Project DB (portable, per project) ORM models. Alembic tree: storage/migrations/project.

Time columns hold integers only (ticks with a time-base string, or frames with a rate);
see the float-seconds schema test.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ProjectBase(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class ProjectMeta(ProjectBase):
    __tablename__ = "project_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Provenance(ProjectBase):
    __tablename__ = "provenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    model_version: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    input_keys: Mapped[list[Any]] = mapped_column(JSON, default=list)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String(40))


class Artifact(ProjectBase):
    """Index of artifact blobs. ``location`` is relative to the artifact store root."""

    __tablename__ = "artifact"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    location: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))
    created_at: Mapped[str] = mapped_column(String(40))
