"""Control DB (app-level) ORM models. Alembic tree: storage/migrations/control."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
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
