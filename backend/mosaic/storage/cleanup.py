"""Project storage: what MosAic keeps for a project, clearing what can be made again, and
removing MosAic's data from a folder (S21; ADR 0051).

- **Regenerable:** previews (proxies and their tick maps) and the render cache (chunks).
  The next analysis or render makes them again from the originals: the proxy stage and
  the chunk tasks check their files, not only the database.
- **Kept:** frames and contact sheets (their stages check database rows, so a missing
  file would never come back), renders (the owner's outputs) and the analysis (the
  database and every other artifact). Clearing never touches durable data (S21).

Removal renames the project's MosAic folders aside (instant, same disk), deletes the
descriptor and forgets the project; the renamed folders are purged in the background.
Originals are never touched (invariant 1): only ``MosAic`` folders, the app-data
workspace and the descriptor file are ever renamed or deleted.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.core.paths import DESCRIPTOR_NAME, WORKSPACE_DIR, app_data_dir
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.registry import task
from mosaic.storage.control import ControlDB
from mosaic.storage.locks import FileLock, LockBusyError
from mosaic.storage.models_control import EditIndex, ProjectRegistry
from mosaic.storage.models_project import Artifact, Render
from mosaic.storage.projects import OPEN_LOCK, PROJECT_DB, PROJECTS_DIR, Project

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    kinds: tuple[str, ...]
    regenerable: bool


# The artifact kinds of each group; every other kind is part of "Analysis".
GROUPS = (
    Group("previews", "Previews", ("proxy", "tickmap"), True),
    Group("render_cache", "Render cache", ("chunk",), True),
    Group("frames", "Frames & contact sheets", ("frame", "mosaic"), False),
)
REGENERABLE = tuple(k for g in GROUPS if g.regenerable for k in g.kinds)
CLEAR_BATCH = 500


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def breakdown(project: Project) -> dict[str, Any]:
    """Bytes per group (S21 Storage). Artifact sizes come from the store's index (one
    query); renders and the database are measured on disk."""
    from mosaic.render.tasks import output_path

    with project.db.session() as s:
        by_kind = dict(
            s.execute(select(Artifact.kind, func.sum(Artifact.size)).group_by(Artifact.kind)).all()
        )
        renders = sum(
            _file_size(output_path(project.workspace, r))
            for r in s.scalars(select(Render).where(Render.path.is_not(None)))
        )
    grouped = {k for g in GROUPS for k in g.kinds}
    db = sum(_file_size(Path(f"{project.live_dir / PROJECT_DB}{x}")) for x in ("", "-wal", "-shm"))
    rows = [
        {
            "id": g.id,
            "label": g.label,
            "bytes": int(sum(by_kind.get(k, 0) or 0 for k in g.kinds)),
            "regenerable": g.regenerable,
        }
        for g in GROUPS
    ]
    rows.append({"id": "renders", "label": "Renders", "bytes": renders, "regenerable": False})
    other = sum(int(v or 0) for k, v in by_kind.items() if k not in grouped)
    rows.append({"id": "analysis", "label": "Analysis", "bytes": db + other, "regenerable": False})
    return {
        "folder": str(project.outputs_dir),
        "total_bytes": sum(r["bytes"] for r in rows),
        "regenerable_bytes": sum(r["bytes"] for r in rows if r["regenerable"]),
        "groups": rows,
    }


# ------------------------------------------------------------------ clearing


def clear_spec() -> list[TaskSpec]:
    return [
        TaskSpec(
            kind="storage.clear",
            stage="storage",
            resource_class=ResourceClass.IO,
            params={},
            label="clearing regenerable files",
        )
    ]


def clear_job(project_id: str) -> JobSpec:
    return JobSpec(project_id=project_id, kind="storage", params={}, tasks=clear_spec())


@task("storage.clear")
def clear_task(ctx: TaskContext) -> dict[str, Any]:
    """Deletes the regenerable artifacts, a batch at a time: the files, then their index
    rows (an artifact counts as present only when both exist)."""
    store = ctx.project.artifacts
    freed = removed = 0
    while True:
        ctx.check_cancelled()
        others = [
            j for j in ctx.store.jobs(ctx.project.id, True, limit=5) if j.id != ctx.task.job_id
        ]
        if others:  # an analysis or render started: never delete what it may be reading
            return {"files": removed, "freed_bytes": freed, "stopped": "other work started"}
        with ctx.project.db.session() as s:
            rows = list(
                s.execute(
                    select(Artifact.key, Artifact.location, Artifact.size)
                    .where(Artifact.kind.in_(REGENERABLE))
                    .limit(CLEAR_BATCH)
                )
            )
        if not rows:
            break
        for _key, location, size in rows:
            (store.root / location).unlink(missing_ok=True)
            freed += size
        with ctx.write() as s:
            s.execute(delete(Artifact).where(Artifact.key.in_([k for k, _, _ in rows])))
        removed += len(rows)
    return {"files": removed, "freed_bytes": freed}


# ------------------------------------------------------------------ moving


def move_job(project_id: str) -> JobSpec:
    """Moves an in-folder trip's live database and cache to app data (ADR 0055): the
    worker's open does it (``open_project`` moves when it may), outside any request."""
    return JobSpec(
        project_id=project_id,
        kind="move",
        params={},
        tasks=[
            TaskSpec(
                kind="project.move",
                stage="moving",
                resource_class=ResourceClass.IO,
                params={},
                label="moving the trip's data to MosAic's storage",
            )
        ],
    )


def ensure_move(store: Any, executor: Any, principal: Any, project_id: str) -> int:
    """The project's running move job, or a new one (never two at once)."""
    moving = store.jobs(project_id, True, kind="move", limit=1)
    if moving:
        return int(moving[0].id)
    return int(executor.submit(principal, move_job(project_id)))


@task("project.move", checkpoint=True)
def move_task(ctx: TaskContext) -> dict[str, Any]:
    """By the time this runs, the worker opened (and so moved) the project."""
    return {"placement": ctx.project.placement.value}


# ------------------------------------------------------------------ removal


class RemovalError(ValueError):
    pass


def _trash_file() -> Path:
    return app_data_dir() / "trash.json"


_trash_lock = threading.Lock()  # the list file
_purge_lock = threading.Lock()  # one purge at a time: two rmtree of one tree trip each other


def _trash_add(paths: Iterable[Path]) -> None:
    with _trash_lock:
        f = _trash_file()
        try:
            listed = json.loads(f.read_text())
        except (OSError, ValueError):
            listed = []
        listed += [str(p) for p in paths]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(sorted(set(listed)), indent=2))


def purge_trash() -> int:
    """Deletes the renamed folders of removed projects (run in the background after a
    removal and at start-up, so an interrupted purge finishes). Returns how many went."""
    with _purge_lock:
        return _purge()


def _purge() -> int:
    with _trash_lock:
        f = _trash_file()
        try:
            listed: list[str] = json.loads(f.read_text())
        except (OSError, ValueError):
            return 0
    gone: list[str] = []
    for p in listed:
        path = Path(p)
        if ".mosaic-removed-" not in path.name:  # only what removal renamed, ever
            gone.append(p)
            continue
        try:
            shutil.rmtree(path)
            gone.append(p)
        except FileNotFoundError:
            gone.append(p)
        except OSError:
            log.warning("could not delete %s yet; will try again at the next start", path)
    with _trash_lock:
        try:
            now: list[str] = json.loads(f.read_text())
        except (OSError, ValueError):
            now = []
        left = [p for p in now if p not in gone]
        if left:
            f.write_text(json.dumps(left, indent=2))
        else:
            f.unlink(missing_ok=True)
    return len(gone)


def purge_in_background() -> threading.Thread:
    t = threading.Thread(target=purge_trash, name="mosaic-purge", daemon=True)
    t.start()
    return t


ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class RemovalBusyError(RemovalError):
    """The project is open elsewhere (a window, the server or a worker)."""


def _owned_dirs(project: Project) -> list[Path]:
    """The folders MosAic made for this project: ``<root>/MosAic`` and the app-data
    workspace ``<app data>/projects/<ULID>``. Anything else is refused (never the footage
    folder, never app data itself: the id comes from a file in the user's folder)."""
    if not ULID.match(project.id):
        raise RemovalError(f"refusing to remove: {project.id!r} is not a project id")
    root = project.root.resolve()
    projects = (app_data_dir() / PROJECTS_DIR).resolve()
    app = (projects / project.id).resolve()
    if app.parent != projects or app.name != project.id:
        raise RemovalError("refusing to remove: the project's app-data folder is not its own")
    out: list[Path] = []
    for d in {project.live_dir, project.outputs_dir}:
        if not d.exists():
            continue
        if d.is_symlink():
            raise RemovalError(f"refusing to remove {d}: it is a link")
        r = d.resolve()
        inside_app = r == app or app in r.parents
        in_folder = r == root / WORKSPACE_DIR
        if not (inside_app or in_folder) or r == root:
            raise RemovalError(f"refusing to remove {d}: not a MosAic folder")
        out.append(app if inside_app else r)
    return sorted(set(out))


def _trash_drop(paths: Iterable[Path]) -> None:
    with _trash_lock:
        f = _trash_file()
        try:
            listed = json.loads(f.read_text())
        except (OSError, ValueError):
            return
        left = [p for p in listed if p not in {str(x) for x in paths}]
        f.write_text(json.dumps(left, indent=2))


def remove_project(control: ControlDB, project: Project, project_id: str) -> list[Path]:
    """Renames the project's MosAic folders aside, deletes its descriptor and forgets it.
    Refused (``RemovalBusyError``) while any other handle has it open. Returns the renamed
    folders (purged by ``purge_trash``); on a failed rename, renamed folders go back."""
    if project.id != project_id:
        raise RemovalError("refusing to remove: the folder holds another project")
    dirs = _owned_dirs(project)
    descriptor = project.root / DESCRIPTOR_NAME
    live = project.live_dir
    project.close(checkpoint=False)
    try:
        lock = FileLock(live / OPEN_LOCK, exclusive=True, blocking=False)
    except LockBusyError:
        raise RemovalBusyError(
            "the project is open in MosAic elsewhere (a window, the server or a worker); "
            "close it, or wait a minute, and try again"
        ) from None
    try:
        stamp = f"{now_iso()[:10]}-{new_ulid()[-6:]}"
        targets = [d.with_name(f".{d.name}.mosaic-removed-{stamp}") for d in dirs]
        _trash_add(targets)  # first: a crash mid-way still gets purged at the next start
        done: list[tuple[Path, Path]] = []
        try:
            for d, target in zip(dirs, targets, strict=True):
                os.rename(d, target)  # same parent: instant, and atomic
                done.append((d, target))
        except OSError as exc:
            # Never purge what is still registered: the list entries go whatever happens.
            _trash_drop(targets)
            stuck = []
            for d, target in reversed(done):
                try:
                    os.rename(target, d)
                except OSError:
                    stuck.append(f"{target} → {d}")
            if stuck:
                raise RemovalError(
                    "MosAic's folder could not be moved aside, nor put back: rename "
                    + "; ".join(stuck)
                    + " yourself, then try again."
                ) from None
            raise RemovalError(
                f"MosAic's folder could not be moved aside ({type(exc).__name__}); nothing "
                "was removed. Close any app using the folder and try again."
            ) from None
    finally:
        lock.release()
    if descriptor.is_file():
        descriptor.unlink()
    with control.db.session() as s:
        s.execute(delete(EditIndex).where(EditIndex.project_id == project.id))
        s.execute(delete(ProjectRegistry).where(ProjectRegistry.project_id == project.id))
    return targets
