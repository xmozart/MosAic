"""Control DB service: installation, the single v1 user, project registry, edit index."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.core.paths import control_db_path
from mosaic.core.principal import Principal
from mosaic.storage.db import Database
from mosaic.storage.models_control import EditIndex, Installation, ProjectRegistry, User

OWNER_USERNAME = "owner"


class ControlDB:
    def __init__(self, path: Path | None = None) -> None:
        self.db = Database(path or control_db_path(), "control", wal=True)
        self._principal = self._ensure_installation()

    def _ensure_installation(self) -> Principal:
        with self.db.session() as s:
            if s.scalar(select(Installation).limit(1)) is None:
                s.add(Installation(installation_id=new_ulid(), created_at=now_iso()))
            user = s.scalar(select(User).where(User.username == OWNER_USERNAME))
            if user is None:
                user = User(username=OWNER_USERNAME, created_at=now_iso())
                s.add(user)
                s.flush()
            return Principal(user_id=user.id)

    @property
    def local_principal(self) -> Principal:
        """v1 is single-user; desktop and CLI act as the owner."""
        return self._principal

    def register_project(
        self,
        principal: Principal,
        *,
        project_id: str,
        name: str,
        root: Path,
        placement: str,
        fs_class: str,
        folder_fingerprint: str | None = None,
    ) -> None:
        with self.db.session() as s:
            row = s.get(ProjectRegistry, project_id)
            now = now_iso()
            if row is None:
                s.add(
                    ProjectRegistry(
                        project_id=project_id,
                        user_id=principal.user_id,
                        name=name,
                        root_path=str(root),
                        placement=placement,
                        fs_class=fs_class,
                        created_at=now,
                        last_opened_at=now,
                        folder_fingerprint=folder_fingerprint,
                    )
                )
            else:
                row.root_path, row.last_opened_at, row.name = str(root), now, name
                row.placement, row.fs_class = placement, fs_class
                row.folder_fingerprint = folder_fingerprint or row.folder_fingerprint

    def find_project(self, root: Path) -> ProjectRegistry | None:
        """The most recently opened project registered for this folder."""
        with self.db.session() as s:
            return s.scalar(
                select(ProjectRegistry)
                .where(ProjectRegistry.root_path == str(root))
                .order_by(ProjectRegistry.last_opened_at.desc())
                .limit(1)
            )

    def find_by_fingerprint(self, fingerprint: str) -> list[ProjectRegistry]:
        """Projects whose folder had this fingerprint (external placement)."""
        with self.db.session() as s:
            return list(
                s.scalars(
                    select(ProjectRegistry).where(ProjectRegistry.folder_fingerprint == fingerprint)
                )
            )

    def project_root(self, project_id: str) -> Path | None:
        with self.db.session() as s:
            row = s.get(ProjectRegistry, project_id)
            return Path(row.root_path) if row else None

    def projects(self, principal: Principal) -> list[ProjectRegistry]:
        with self.db.session() as s:
            q = select(ProjectRegistry).where(ProjectRegistry.user_id == principal.user_id)
            return list(s.scalars(q.order_by(ProjectRegistry.last_opened_at.desc())))

    def index_edit(self, principal: Principal, edit_id: str, project_id: str) -> None:
        with self.db.session() as s:
            if s.get(EditIndex, edit_id) is None:
                s.add(EditIndex(edit_id=edit_id, project_id=project_id, user_id=principal.user_id))

    def project_for_edit(self, edit_id: str) -> str | None:
        with self.db.session() as s:
            row = s.get(EditIndex, edit_id)
            return row.project_id if row else None
