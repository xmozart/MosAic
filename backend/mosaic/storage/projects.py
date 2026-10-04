"""Create and open projects (ARCHITECTURE.md §4). M0 supports in-folder placement only."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.core.paths import WORKSPACE_DIR
from mosaic.core.principal import Principal, check
from mosaic.storage.artifacts import ArtifactStore
from mosaic.storage.control import ControlDB
from mosaic.storage.db import Database
from mosaic.storage.descriptor import ProjectDescriptor, read_descriptor, write_descriptor
from mosaic.storage.models_project import ProjectMeta
from mosaic.storage.placement import (
    Classification,
    Placement,
    PlacementRefusedError,
    classify,
    require_supported,
)

PROJECT_DB = "project.db"


class NotAProjectError(RuntimeError):
    pass


@dataclass
class Project:
    root: Path
    descriptor: ProjectDescriptor
    db: Database
    artifacts: ArtifactStore

    @property
    def id(self) -> str:
        return self.descriptor.project_id

    @property
    def workspace(self) -> Path:
        return self.root / WORKSPACE_DIR

    @contextmanager
    def write(self) -> Iterator[Session]:
        """The project's single writer (ARCHITECTURE.md §7). Do not record artifacts or
        open another write while it is held."""
        with self.artifacts.gate.hold(), self.db.session() as s:
            yield s

    def close(self) -> None:
        self.db.dispose()


def preview(folder: Path) -> Classification:
    """Classify a folder without writing anything (``POST /projects/preview``)."""
    return classify(folder.expanduser().resolve())


def _require_in_folder(descriptor: ProjectDescriptor) -> None:
    if descriptor.placement is not Placement.IN_FOLDER:
        raise PlacementRefusedError(
            f"this project uses {descriptor.placement.value} placement, which arrives in a "
            "later version"
        )


def _open_handles(root: Path, descriptor: ProjectDescriptor) -> Project:
    workspace = root / WORKSPACE_DIR
    db = Database(workspace / PROJECT_DB, "project", wal=True)
    with db.session() as s:
        if s.get(ProjectMeta, "project_id") is None:
            s.add(ProjectMeta(key="project_id", value=descriptor.project_id))
    return Project(root, descriptor, db, ArtifactStore(workspace / "cache", db))


def _register(
    control: ControlDB, principal: Principal, root: Path, d: ProjectDescriptor, c: Classification
) -> None:
    control.register_project(
        principal,
        project_id=d.project_id,
        name=d.name,
        root=root,
        placement=d.placement.value,
        fs_class=c.fs_class.value,
    )


def init_project(
    control: ControlDB, principal: Principal, folder: Path, name: str | None = None
) -> Project:
    """Create (or re-open) the project for ``folder``. Only ``local`` placement in M0."""
    root = folder.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a folder: {root}")
    check(principal, "project.create", str(root))
    classification = classify(root)
    require_supported(classification)
    descriptor = read_descriptor(root)
    if descriptor is None:
        descriptor = ProjectDescriptor(
            project_id=new_ulid(),
            name=name or root.name,
            placement=Placement.IN_FOLDER,
            created_at=now_iso(),
        )
        (root / WORKSPACE_DIR).mkdir(exist_ok=True)
        write_descriptor(root, descriptor)
    _require_in_folder(descriptor)
    project = _open_handles(root, descriptor)
    _register(control, principal, root, descriptor, classification)
    return project


def open_project(control: ControlDB, principal: Principal, folder: Path) -> Project:
    root = folder.expanduser().resolve()
    descriptor = read_descriptor(root)
    if descriptor is None:
        raise NotAProjectError(f"{root} is not a MosAic project; run `mosaic init {root}`")
    check(principal, "project.open", descriptor.project_id)
    classification = classify(root)
    require_supported(classification)
    _require_in_folder(descriptor)
    project = _open_handles(root, descriptor)
    _register(control, principal, root, descriptor, classification)
    return project
