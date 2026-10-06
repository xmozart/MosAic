"""Media roots and path confinement for server mode (ARCHITECTURE.md §14; ADR 0035).

A server only lists, opens or scans folders inside its media roots. Every path from a
client is canonicalised (symlinks resolved) and must stay inside a root: relative paths
with ``..``, absolute paths elsewhere and symlinks that escape are all refused the same
way. Roots come from the admin (S22) and from ``MOSAIC_MEDIA_ROOTS`` at start-up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import MediaRoot

ENV_ROOTS = "MOSAIC_MEDIA_ROOTS"


class PathRefusedError(ValueError):
    """Not a usable path (unknown root, invalid characters); names no real path."""


class PathOutsideRootError(PathRefusedError):
    """Resolves outside the media root(s): traversal, an absolute path, an escaping link."""


@dataclass(frozen=True)
class Root:
    id: int
    path: Path
    label: str
    source: str


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def roots(control: ControlDB) -> list[Root]:
    with control.db.session() as s:
        return [
            Root(r.id, Path(r.path), r.label, r.source)
            for r in s.scalars(select(MediaRoot).order_by(MediaRoot.label, MediaRoot.id))
        ]


def add(control: ControlDB, path: str, label: str | None = None, source: str = "admin") -> Root:
    p = Path(path)
    if not p.is_absolute():
        raise PathRefusedError("Use the folder's full path.")
    canon = _canonical(p)
    if not canon.is_dir():
        raise PathRefusedError("That folder doesn't exist on the server.")
    with control.db.session() as s:
        existing = s.scalar(select(MediaRoot).where(MediaRoot.path == str(canon)))
        if existing is None:
            existing = MediaRoot(
                path=str(canon),
                label=label or canon.name or str(canon),
                source=source,
                created_at=now_iso(),
            )
            s.add(existing)
            s.flush()
        return Root(existing.id, Path(existing.path), existing.label, existing.source)


def remove(control: ControlDB, root_id: int) -> bool:
    with control.db.session() as s:
        row = s.get(MediaRoot, root_id)
        if row is None:
            return False
        s.delete(row)
        return True


def seed_from_env(control: ControlDB) -> None:
    """``MOSAIC_MEDIA_ROOTS``: folders separated by the OS path separator (``:``)."""
    for item in os.environ.get(ENV_ROOTS, "").split(os.pathsep):
        if item.strip():
            try:
                add(control, item.strip(), source="env")
            except PathRefusedError:
                continue  # a missing mount: the admin sees fewer roots, not a crash


def get(control: ControlDB, root_id: int) -> Root:
    for r in roots(control):
        if r.id == root_id:
            return r
    raise PathRefusedError("Unknown media root.")


def within(root: Root, rel: str) -> Path:
    """``rel`` (a path relative to ``root``) as a real folder path inside the root."""
    if "\x00" in rel:
        raise PathRefusedError("Invalid path.")
    parts = PurePosixPath(rel.replace("\\", "/"))
    drive = os.name == "nt" and len(rel) > 1 and rel[0].isalpha() and rel[1] == ":"
    if parts.is_absolute() or drive:
        raise PathOutsideRootError("Use a path inside the media root.")
    base = _canonical(root.path)
    try:
        target = _canonical(base.joinpath(*parts.parts)) if parts.parts else base
    except (OSError, RuntimeError):  # a name too long, a symlink loop
        raise PathRefusedError("Invalid path.") from None
    if not target.is_relative_to(base):
        raise PathOutsideRootError("That path is outside the media root.")
    return target


def confine(control: ControlDB, path: str) -> tuple[Root, Path]:
    """An absolute path from a client, if it lies inside some media root."""
    if "\x00" in path:
        raise PathRefusedError("Invalid path.")
    p = Path(path)
    if not p.is_absolute():
        raise PathOutsideRootError("Use the folder's full path.")
    try:
        target = _canonical(p)
    except (OSError, RuntimeError):
        raise PathRefusedError("Invalid path.") from None
    for r in roots(control):
        base = _canonical(r.path)
        if target.is_relative_to(base):
            return r, target
    raise PathOutsideRootError("That folder is outside the media roots.")


def relative(root: Root, path: Path) -> str:
    """The client-facing path: relative to the root, POSIX separators (§14)."""
    rel = _canonical(path).relative_to(_canonical(root.path))
    return "" if str(rel) == "." else rel.as_posix()
