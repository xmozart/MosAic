"""Create and open projects (ARCHITECTURE.md §4, ADR 0022).

Each project has two locations:

- **live**: the live project DB and the artifact cache. They are always on a local
  filesystem (invariant 2).
- **outputs**: edit JSON exports, renders and DB snapshots, which the user keeps with the
  footage.

| placement | live | outputs | descriptor |
|---|---|---|---|
| ``in_folder`` | ``<root>/MosAic`` | ``<root>/MosAic`` | ``<root>/.mosaic-project.json`` |
| ``split`` | app data ``projects/<id>`` | ``<root>/MosAic`` | ``<root>/.mosaic-project.json`` |
| ``external`` | app data ``projects/<id>`` | app data ``projects/<id>/outputs`` | app data |

Split projects:

- **Snapshots.** The live DB is snapshotted into ``<root>/MosAic/project.db`` at
  checkpoints (``Project.checkpoint``). A sidecar ``project.db.json`` records the
  project id and a **generation** that increases with every snapshot.
- **Seeding.** A folder opened without a live DB is seeded from its snapshot. A live DB
  that is older than the folder's snapshot, and has no unsnapshotted changes, is replaced
  by it. One that has unsnapshotted changes is refused, rather than either side losing
  work.

External projects (read-only folders) are found by folder path, or, after the folder
moves, by a fingerprint of its contents.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.core.paths import DESCRIPTOR_NAME, WORKSPACE_DIR, app_data_dir
from mosaic.core.principal import Principal, check
from mosaic.storage import lease
from mosaic.storage.artifacts import ArtifactStore
from mosaic.storage.control import ControlDB
from mosaic.storage.db import Database
from mosaic.storage.descriptor import ProjectDescriptor, read_descriptor, write_descriptor
from mosaic.storage.locks import FileLock, LockBusyError, fsync_file, locked
from mosaic.storage.models_project import ProjectMeta
from mosaic.storage.placement import (
    Classification,
    FsClass,
    Placement,
    PlacementRefusedError,
    classify,
    folder_db_forbidden,
)
from mosaic.storage.sqlite_engine import backup

log = logging.getLogger(__name__)

PROJECT_DB = "project.db"
SNAPSHOT_META = "project.db.json"
PROJECTS_DIR = "projects"
OPEN_LOCK = ".open.lock"
CHECKPOINT_LOCK = ".checkpoint.lock"
STATE_FILE = ".snapshot-state.json"  # live side: generation and DB signature at last snapshot
GENERATION = "generation"
FINGERPRINT_FILES = 256  # files sampled for an external project's folder fingerprint
OPEN_WAIT_S = 60.0  # longest wait for another opener's seeding (a snapshot copy)
STALE_TEMP_S = 3600  # leftover snapshot temp files older than this are swept on open


class NotAProjectError(RuntimeError):
    pass


class ProjectBusyError(RuntimeError):
    """The project is open elsewhere (another process or window)."""


class SnapshotConflictError(RuntimeError):
    """This computer's live DB and the folder's newer snapshot both have changes."""


class MoveNeededError(RuntimeError):
    """The trip keeps its live database in its folder, which can't be used here: it must
    be moved to split first. The move copies its cache (often many GB), so a request never
    does it; a job does (``project.move``; ADR 0055). The project is registered already."""

    def __init__(self, project_id: str, message: str) -> None:
        super().__init__(message)
        self.project_id = project_id


class ReadOnlyProjectError(RuntimeError):
    """A write to a project opened read-only (it is open for editing elsewhere)."""


def local_dir(project_id: str) -> Path:
    """A project's local workspace in app data (split and external placements)."""
    return app_data_dir() / PROJECTS_DIR / project_id


def locations(placement: Placement, root: Path, project_id: str) -> tuple[Path, Path]:
    """(live, outputs) directories for a placement. The descriptor's ``workspace`` field
    is fixed to ``MosAic`` in this format version."""
    if placement is Placement.IN_FOLDER:
        return root / WORKSPACE_DIR, root / WORKSPACE_DIR
    if placement is Placement.SPLIT:
        return local_dir(project_id), root / WORKSPACE_DIR
    return local_dir(project_id), local_dir(project_id) / "outputs"


def _db_signature(live: Path) -> list[int]:
    """Size and mtime of the DB and its WAL: they change with every committed write."""
    out: list[int] = []
    for suffix in ("", "-wal"):
        try:
            st = Path(f"{live / PROJECT_DB}{suffix}").stat()
            out += [st.st_size, st.st_mtime_ns]
        except FileNotFoundError:
            out += [0, 0]
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    part = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    try:
        part.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


@dataclass
class Project:
    root: Path
    descriptor: ProjectDescriptor
    db: Database
    artifacts: ArtifactStore
    live_dir: Path
    outputs_dir: Path
    read_only: bool = False
    _open_lock: FileLock | None = field(default=None, repr=False)
    _checkpoint_mutex: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def id(self) -> str:
        return self.descriptor.project_id

    @property
    def placement(self) -> Placement:
        return self.descriptor.placement

    @property
    def workspace(self) -> Path:
        """Where the user's outputs go: edit exports and renders."""
        return self.outputs_dir

    @contextmanager
    def write(self) -> Iterator[Session]:
        """The project's single writer (ARCHITECTURE.md §7). Do not record artifacts or
        open another write while it is held."""
        if self.read_only:
            raise ReadOnlyProjectError(
                "this project is open read-only (it is being edited on another computer)"
            )
        with self.artifacts.gate.hold(), self.db.session() as s:
            yield s

    def checkpoint(self) -> Path | None:
        """Snapshot the live DB into the folder (split placement only; ARCHITECTURE.md §4):
        after a stage (opt-in per task), an edit commit, and on close.

        - Nothing is published when the DB did not change since the last snapshot. File
          stats are the cheap test. When they differ (a write, or SQLite merging its WAL
          on close), a local backup's digest decides.
        - A newer snapshot from another computer is never overwritten."""
        if self.placement is not Placement.SPLIT or self.read_only:
            return None
        if not self.outputs_dir.is_dir():
            return None  # MosAic's data was removed from the folder (ADR 0051): never recreate it
        dest = self.outputs_dir / PROJECT_DB
        state_path = self.live_dir / STATE_FILE
        with self._checkpoint_mutex, locked(self.live_dir / CHECKPOINT_LOCK):
            state = _read_json(state_path) or {}
            signature = _db_signature(self.live_dir)
            if state.get("signature") == signature and dest.is_file():
                return None
            generation = int(state.get(GENERATION, 0))
            theirs = _read_json(self.outputs_dir / SNAPSHOT_META) or {}
            if theirs.get("project_id") == self.id and int(theirs.get(GENERATION, 0)) > generation:
                log.warning(
                    "project %s: the folder holds a newer snapshot (generation %s > %s) from "
                    "another computer; not overwriting it",
                    self.id,
                    theirs.get(GENERATION),
                    generation,
                )
                return None
            scratch = self.live_dir / f".snapshot-{uuid.uuid4().hex}.db"
            try:
                backup(self.db.path, scratch)
                digest = _file_digest(scratch)
                if digest == state.get("digest") and dest.is_file():
                    _write_json(state_path, state | {"signature": signature})
                    return None
                generation += 1
                _publish(scratch, dest)
            finally:
                scratch.unlink(missing_ok=True)
            _write_json(
                self.outputs_dir / SNAPSHOT_META,
                {"project_id": self.id, GENERATION: generation, "written_at": now_iso()},
            )
            _write_json(
                state_path, {GENERATION: generation, "signature": signature, "digest": digest}
            )
        return dest

    def close(self, *, checkpoint: bool = True) -> None:
        """Close the project. Request-scoped handles (API reads and writes) pass
        ``checkpoint=False``: snapshots follow stages, edit commits and real closes."""
        try:
            if checkpoint:
                self.checkpoint()
        except Exception:
            log.exception("snapshot of project %s on close failed; the live DB is intact", self.id)
        finally:
            self.db.dispose()
            if self._open_lock is not None:
                self._open_lock.release()
                self._open_lock = None


def preview(folder: Path) -> Classification:
    """Classify a folder without writing anything (``POST /projects/preview``)."""
    return classify(folder.expanduser().resolve())


def folder_fingerprint(root: Path) -> str | None:
    """A fingerprint of a folder's contents that survives a move: relative paths and sizes
    of the first ``FINGERPRINT_FILES`` files in sorted walk order (hidden entries and the
    workspace are skipped). Reads no file contents. None for a folder with no such files."""
    h = hashlib.sha256()
    n = 0
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != WORKSPACE_DIR)
        for name in sorted(f for f in files if not f.startswith(".")):
            path = Path(here) / name
            try:
                size = path.lstat().st_size
            except OSError:
                continue
            h.update(f"{path.relative_to(root).as_posix()}\0{size}\n".encode())
            n += 1
            if n >= FINGERPRINT_FILES:
                return h.hexdigest()
    return h.hexdigest() if n else None


def check_placement(placement: Placement, c: Classification) -> None:
    """A placement the folder's class allows (ARCHITECTURE.md §4 override rules)."""
    if placement is Placement.IN_FOLDER and c.fs_class in (
        FsClass.NETWORK,
        FsClass.CLOUD_SYNCED,
    ):
        raise PlacementRefusedError(
            f"in-folder placement keeps the live database in the folder, but {c.reason}: "
            "a database there can be corrupted by the network or by sync. Use split placement."
        )
    if placement is Placement.IN_FOLDER and folder_db_forbidden():
        raise PlacementRefusedError(
            "this server keeps live databases in its own data folder (MOSAIC_FOLDER_DB=never); "
            "use split placement"
        )
    if placement is not Placement.EXTERNAL and c.fs_class is FsClass.READ_ONLY:
        raise PlacementRefusedError(
            "the folder is read-only, so nothing can be written next to the footage; "
            "use external placement"
        )


def _external_descriptor_dir(project_id: str) -> Path:
    return local_dir(project_id)


def _save_descriptor(root: Path, d: ProjectDescriptor) -> None:
    if d.placement is Placement.EXTERNAL:
        target = _external_descriptor_dir(d.project_id)
        target.mkdir(parents=True, exist_ok=True)
        write_descriptor(target, d)
    else:
        write_descriptor(root, d)


MAX_NAME = 120


def rename_project(control: ControlDB, project: Project, name: str) -> str:
    """The project's display name, in its descriptor and the registry (S0 header, S21).
    The folder is never renamed."""
    clean = " ".join(name.split())
    if not clean or len(clean) > MAX_NAME:
        raise ValueError(f"a name has 1–{MAX_NAME} characters")
    if project.read_only:
        raise ReadOnlyProjectError("this project is open read-only")
    d = project.descriptor.model_copy(update={"name": clean})
    _save_descriptor(project.root, d)
    project.descriptor = d
    control.rename_project(project.id, clean)
    return clean


def _sweep_temp(*dirs: Path) -> None:
    """Remove snapshot temp files an interrupted run left behind."""
    cutoff = time.time() - STALE_TEMP_S
    for d in dirs:
        if not d.is_dir():
            continue
        for p in [*d.glob(".snapshot-*.db"), *d.glob(f"{PROJECT_DB}.*.part")]:
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish(scratch: Path, dest: Path) -> None:
    """Copy a local snapshot into the folder as a plain file (SQLite never opens it there),
    through a unique part file renamed into place."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.part")
    try:
        shutil.copyfile(scratch, part)
        fsync_file(part)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)


def _unchanged_since_snapshot(live: Path, state: dict[str, Any]) -> bool:
    if state.get("signature") == _db_signature(live):
        return True
    scratch = live / f".snapshot-{uuid.uuid4().hex}.db"
    try:
        backup(live / PROJECT_DB, scratch)
        return _file_digest(scratch) == state.get("digest")
    finally:
        scratch.unlink(missing_ok=True)


def _move_aside(live: Path) -> None:
    aside = live / f"replaced-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    aside.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(f"{live / PROJECT_DB}{suffix}")
        if src.exists():
            os.replace(src, aside / src.name)


def _seed(live: Path, outputs: Path, project_id: str, *, refresh: bool = True) -> None:
    """Seed or refresh a split project's live DB from the folder's snapshot (§4). An
    existing live DB is replaced only with ``refresh`` (no other handle has it open)."""
    target = live / PROJECT_DB
    snap = outputs / PROJECT_DB
    theirs = _read_json(outputs / SNAPSHOT_META)
    if not snap.is_file() or theirs is None or theirs.get("project_id") != project_id:
        return  # no snapshot, or one copied in from another project: never used
    their_gen = int(theirs.get(GENERATION, 0))
    if target.exists() and not refresh:
        state = _read_json(live / STATE_FILE) or {}
        if their_gen > int(state.get(GENERATION, 0)):
            log.info(
                "project %s: the folder has a newer snapshot; it is picked up when the "
                "project is no longer open elsewhere in MosAic",
                project_id,
            )
        return
    if target.exists():
        state = _read_json(live / STATE_FILE) or {}
        mine = int(state.get(GENERATION, 0))
        if their_gen <= mine:
            return
        if not _unchanged_since_snapshot(live, state):
            raise SnapshotConflictError(
                "this project was changed on this computer and, since then, on another one "
                f"(the folder's snapshot is newer). Its live database is kept at {live}; "
                "copy what you need, then remove it to continue from the folder's snapshot."
            )
        _move_aside(live)  # unchanged here since our last snapshot: theirs supersedes it
    live.mkdir(parents=True, exist_ok=True)
    part = live / f"{PROJECT_DB}.{uuid.uuid4().hex}.part"
    try:
        shutil.copyfile(snap, part)  # a plain copy: SQLite never opens the folder's file
        fsync_file(part)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    # The seeded file is the snapshot itself (a backup in DELETE mode), so its digest is
    # what a backup of it gives: closing it unchanged publishes nothing.
    _write_json(
        live / STATE_FILE,
        {GENERATION: their_gen, "signature": _db_signature(live), "digest": _file_digest(target)},
    )


def _open_handles(root: Path, d: ProjectDescriptor) -> Project:
    live, outputs = locations(d.placement, root, d.project_id)
    live.mkdir(parents=True, exist_ok=True)
    # Exclusive first: only a sole opener may replace the live DB from a newer snapshot
    # (another handle would keep writing to the replaced file). Then shared for the
    # project's lifetime; relocation needs it exclusively.
    try:
        open_lock = FileLock(live / OPEN_LOCK, exclusive=True, blocking=False)
        sole = True
    except LockBusyError:
        try:
            # Another opener holds it exclusively for a moment (while it seeds), or a
            # relocation does: wait; the descriptor re-check below detects a relocation.
            open_lock = FileLock(
                live / OPEN_LOCK, exclusive=False, blocking=False, timeout_s=OPEN_WAIT_S
            )
        except LockBusyError:
            raise ProjectBusyError(f"project {d.project_id} is being moved; try again") from None
        sole = False
    try:
        current = _current_descriptor(root, d)
        if current is None or current.placement is not d.placement:
            raise ProjectBusyError(f"project {d.project_id} was just moved; open it again")
        if d.placement is Placement.SPLIT:
            with locked(live / CHECKPOINT_LOCK):
                _seed(live, outputs, d.project_id, refresh=sole)
        if sole:
            open_lock.downgrade()
        if d.placement is Placement.SPLIT:
            _sweep_temp(live, outputs)
        outputs.mkdir(parents=True, exist_ok=True)
        db = Database(live / PROJECT_DB, "project", wal=True)
        with db.session() as s:
            if s.get(ProjectMeta, "project_id") is None:
                s.add(ProjectMeta(key="project_id", value=d.project_id))
    except BaseException:
        open_lock.release()
        raise
    artifacts = ArtifactStore(live / "cache", db)
    return Project(root, d, db, artifacts, live, outputs, _open_lock=open_lock)


def _current_descriptor(root: Path, d: ProjectDescriptor) -> ProjectDescriptor | None:
    """The descriptor as it is now (a relocation may have finished since it was read)."""
    if d.placement is Placement.EXTERNAL:
        return read_descriptor(_external_descriptor_dir(d.project_id))
    return read_descriptor(root)


def _register(
    control: ControlDB,
    principal: Principal,
    root: Path,
    d: ProjectDescriptor,
    c: Classification,
    fingerprint: str | None,
) -> None:
    control.register_project(
        principal,
        project_id=d.project_id,
        name=d.name,
        root=root,
        placement=d.placement.value,
        fs_class=c.fs_class.value,
        folder_fingerprint=fingerprint,
    )


def _find_descriptor(control: ControlDB, root: Path) -> tuple[ProjectDescriptor | None, str | None]:
    """The folder's descriptor, or an external project's: by the folder's path first, then
    by its fingerprint (computed only then), which matches only a project whose folder is
    gone (it moved), never a second copy that still exists."""
    d = read_descriptor(root)
    if d is not None:
        return d, None
    row = control.find_project(root)
    fingerprint = None
    if row is None:
        fingerprint = folder_fingerprint(root)
        if fingerprint is not None:
            moved = [
                r
                for r in control.find_by_fingerprint(fingerprint)
                if not Path(r.root_path).is_dir()
            ]
            row = moved[0] if len(moved) == 1 else None
    if row is None or row.placement != Placement.EXTERNAL.value:
        return None, fingerprint
    return read_descriptor(_external_descriptor_dir(row.project_id)), fingerprint


def _copy_tree(src: Path, dst: Path, skip: set[str]) -> list[Path]:
    """Merge ``src`` into ``dst``: top-level files already at ``dst`` are kept, folders
    are merged (files inside them are overwritten). Returns what was copied."""
    copied: list[Path] = []
    if not src.is_dir() or src == dst:
        return copied
    for item in src.iterdir():
        if item.name in skip or item.name.startswith((f"{PROJECT_DB}", ".")):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif not target.exists():
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        copied.append(item)
    return copied


def _remove(paths: list[Path]) -> None:
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
        except OSError as exc:  # e.g. the old folder is now read-only: leave it
            log.warning("could not remove %s after relocation: %s", p, exc)


def _relocate(root: Path, old: ProjectDescriptor, new: Placement) -> ProjectDescriptor:
    """Move a project to another placement, crash-safely: copy the DB (backup API) and the
    cache and outputs, write the new descriptor, and only then delete the old copies.
    Refused while the project is open anywhere. Original footage is never touched."""
    old_live, old_out = locations(old.placement, root, old.project_id)
    new_live, new_out = locations(new, root, old.project_id)
    old_live.mkdir(parents=True, exist_ok=True)
    relocated = False
    try:
        lock = FileLock(old_live / OPEN_LOCK, exclusive=True, blocking=False)
    except LockBusyError:
        raise ProjectBusyError(
            "the project is open in MosAic (a window, the server or a worker); close it and "
            "try again"
        ) from None
    try:
        new_live.mkdir(parents=True, exist_ok=True)
        new_out.mkdir(parents=True, exist_ok=True)
        if old.placement is Placement.SPLIT:
            # Never move away from a stale copy: take the folder's newer snapshot first, or
            # stop on a conflict (both sides changed).
            with locked(old_live / CHECKPOINT_LOCK):
                _seed(old_live, old_out, old.project_id)
        old_db = old_live / PROJECT_DB
        leftovers: list[Path] = []
        if old_db.is_file() and old_live != new_live:
            part = new_live / f"{PROJECT_DB}.{uuid.uuid4().hex}.part"
            try:
                try:
                    backup(old_db, part)
                except sqlite3.OperationalError:  # e.g. the old folder became read-only
                    backup(old_db, part, read_only_source=True)
                os.replace(part, new_live / PROJECT_DB)
            finally:
                part.unlink(missing_ok=True)
            leftovers += [Path(f"{old_db}{x}") for x in ("", "-wal", "-shm")]
            leftovers += [old_live / STATE_FILE]
        if old_live != new_live and (old_live / "cache").is_dir():
            shutil.copytree(old_live / "cache", new_live / "cache", dirs_exist_ok=True)
            leftovers.append(old_live / "cache")
        if old_out != new_out:
            leftovers += _copy_tree(old_out, new_out, skip={"cache"})
        if new is not Placement.SPLIT:  # snapshots belong to split projects only
            for name in (PROJECT_DB, SNAPSHOT_META):
                if (new_out / name).exists() and new_out != new_live:
                    leftovers.append(new_out / name)
            if old.placement is Placement.SPLIT:
                leftovers.append(old_out / SNAPSHOT_META)
        moved = old.model_copy(update={"placement": new})
        _save_descriptor(root, moved)  # from here on, the new copy is the project
        if new is Placement.EXTERNAL:
            leftovers.append(root / DESCRIPTOR_NAME)
        if old.placement is Placement.EXTERNAL:
            leftovers.append(_external_descriptor_dir(old.project_id) / DESCRIPTOR_NAME)
        _remove([p for p in leftovers if p.exists()])
        relocated = True
        return moved
    finally:
        lock.release()
        if relocated and old_live != new_live:  # only once the project lives elsewhere
            for name in (OPEN_LOCK, CHECKPOINT_LOCK):
                (old_live / name).unlink(missing_ok=True)


def _take_lease(control: ControlDB, project: Project, take_over: bool) -> None:
    try:
        lease.acquire(project.outputs_dir, control.installation_id, force=take_over)
    except BaseException:
        project.close(checkpoint=False)
        raise


_MOVE_MESSAGE = (
    "This trip's data has to move out of its folder before it can be used here (its live "
    "database can't stay there). If it isn't moving now, open the trip from Home to move it"
)


def _move(
    control: ControlDB,
    root: Path,
    descriptor: ProjectDescriptor,
    wanted: Placement,
    take_over: bool,
) -> ProjectDescriptor:
    """Relocate under the project's lease (never move it under another computer)."""
    _, out = locations(descriptor.placement, root, descriptor.project_id)
    lease.acquire(out, control.installation_id, force=take_over)
    moved = _relocate(root, descriptor, wanted)
    if locations(wanted, root, descriptor.project_id)[1] != out:
        lease.release(out, control.installation_id)
    return moved


def init_project(
    control: ControlDB,
    principal: Principal,
    folder: Path,
    name: str | None = None,
    placement: Placement | None = None,
    *,
    take_over: bool = False,
    move: bool = True,
) -> Project:
    """Create (or re-open) the project for ``folder``. ``placement`` overrides the policy
    (Advanced settings); an existing project is moved to it."""
    root = folder.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a folder: {root}")
    check(principal, "project.create", str(root))
    c = classify(root)
    descriptor, fingerprint = _find_descriptor(control, root)
    wanted = placement or (descriptor.placement if descriptor else c.placement)
    if placement is None and wanted is Placement.IN_FOLDER and c.placement is Placement.SPLIT:
        # A trip made in-folder elsewhere, opened where its folder can't hold a live
        # database (a host share, or a server that keeps them in app data): moved to split,
        # its live database to app data, a snapshot left in the folder (ADR 0055).
        wanted = Placement.SPLIT
        if descriptor is not None and not move:
            _register(control, principal, root, descriptor, c, fingerprint)
            raise MoveNeededError(descriptor.project_id, _MOVE_MESSAGE)
    check_placement(wanted, c)
    if descriptor is None:
        descriptor = ProjectDescriptor(
            project_id=new_ulid(),
            name=name or root.name,
            placement=wanted,
            created_at=now_iso(),
        )
        _save_descriptor(root, descriptor)
    elif descriptor.placement is not wanted:
        descriptor = _move(control, root, descriptor, wanted, take_over)
    if wanted is Placement.EXTERNAL and fingerprint is None:
        fingerprint = folder_fingerprint(root)
    project = _open_handles(root, descriptor)
    _take_lease(control, project, take_over)
    _register(control, principal, root, descriptor, c, fingerprint)
    return project


def open_project(
    control: ControlDB,
    principal: Principal,
    folder: Path,
    *,
    read_only: bool = False,
    take_over: bool = False,
    move: bool = True,
) -> Project:
    """Open a project for editing, which takes (or renews) its lease and raises
    ``lease.LeaseHeldError`` if another computer holds it; or ``read_only``, which never
    takes the lease and refuses writes."""
    root = folder.expanduser().resolve()
    descriptor, fingerprint = _find_descriptor(control, root)
    if descriptor is None:
        raise NotAProjectError(f"{root} is not a MosAic project; run `mosaic init {root}`")
    check(principal, "project.open", descriptor.project_id)
    c = classify(root)
    if descriptor.placement is Placement.IN_FOLDER and c.placement is Placement.SPLIT:
        # Made in-folder elsewhere; here the folder can't hold a live database (a host
        # share, or a server that keeps them in app data): moved to split (ADR 0055).
        if not move:
            _register(control, principal, root, descriptor, c, fingerprint)
            raise MoveNeededError(descriptor.project_id, _MOVE_MESSAGE)
        if read_only:
            raise PlacementRefusedError(
                "this trip keeps its live database in its folder, which can't be used from "
                "here; open it for editing once to move the database to MosAic's data"
            )
        descriptor = _move(control, root, descriptor, Placement.SPLIT, take_over)
    check_placement(descriptor.placement, c)
    if descriptor.placement is Placement.EXTERNAL and fingerprint is None:
        fingerprint = folder_fingerprint(root)
    project = _open_handles(root, descriptor)
    project.read_only = read_only
    project.artifacts.read_only = read_only
    if not read_only:
        _take_lease(control, project, take_over)
    _register(control, principal, root, descriptor, c, fingerprint)
    return project
