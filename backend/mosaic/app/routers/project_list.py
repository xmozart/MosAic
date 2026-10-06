"""Recents, folder preview and project creation (S3, S4; API_MAP "Projects"; ADR 0038).

``GET /projects`` reads only the control DB: each project's card is written at
checkpoints (``storage.project_cards``), so listing opens no project DB. A missing folder
is detected with a short, parallel check so one offline share never blocks the list.

Folders arrive as an absolute ``path`` on desktop, or as ``{root, path}`` (a media root and
a path inside it) on a server; both go through the same confinement gate (ADR 0035).
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, wait
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.clock import now_iso
from mosaic.core.paths import DESCRIPTOR_NAME
from mosaic.core.principal import Principal, check
from mosaic.core.runtime import server_mode
from mosaic.jobs.model import JOB_TERMINAL
from mosaic.media.pipeline import submit_scan
from mosaic.media.scan import quick_counts
from mosaic.storage import media_roots, project_cards
from mosaic.storage.descriptor import read_descriptor
from mosaic.storage.placement import PLACEMENT_FOR_CLASS, Placement, PlacementRefusedError
from mosaic.storage.projects import NotAProjectError, init_project, open_project, preview

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)

MISSING_CHECK_S = 0.5  # per list request, all folders checked in parallel
PREVIEW_MAX_ENTRIES = 50_000  # a quick look, not a scan


class FolderRef(BaseModel):
    """Desktop: ``path`` (absolute). Server: ``root`` (a media root id) and ``path``
    inside it."""

    model_config = ConfigDict(extra="forbid")

    root: int | None = None
    path: str = Field(default="", max_length=4096)


class CreateBody(FolderRef):
    name: str | None = Field(default=None, max_length=120)
    placement: Placement | None = None


def _folder(svc: Services, ref: FolderRef) -> Path:
    try:
        if server_mode():
            if ref.root is None:
                raise HTTPException(422, "Choose a folder inside a media root.")
            return media_roots.within(media_roots.get(svc.control, ref.root), ref.path)
        if ref.root is not None:
            raise HTTPException(422, "Use the folder's full path.")
        p = Path(ref.path).expanduser()
        if not p.is_absolute():
            raise HTTPException(422, "Use the folder's full path.")
        return p.resolve()
    except media_roots.PathOutsideRootError as exc:
        raise HTTPException(403, str(exc)) from None
    except media_roots.PathRefusedError as exc:
        raise HTTPException(404, str(exc)) from None


def _known_project(svc: Services, folder: Path) -> str | None:
    """The project already made for this folder: its descriptor, or — for external
    placement, which writes nothing into the folder — the control DB's registry (no writes)."""
    if (folder / DESCRIPTOR_NAME).is_file():
        try:
            d = read_descriptor(folder)
        except Exception:  # an unreadable descriptor: let creation report it
            return None
        return d.project_id if d is not None else None
    row = svc.control.find_project(folder.resolve())
    # Only external projects live without a descriptor; a registered in-folder project
    # whose descriptor is gone is made again (init_project), like _find_descriptor does.
    if row is not None and row.placement == Placement.EXTERNAL.value:
        return row.project_id
    return None


def _client_path(svc: Services, folder: Path) -> dict[str, Any]:
    """Where a project lives, as this client may see it (no server paths, §14)."""
    if not server_mode():
        return {"root": None, "path": str(folder)}
    try:
        r, inside = media_roots.confine(svc.control, str(folder))
    except media_roots.PathRefusedError:
        return {"root": None, "path": None}
    return {"root": r.id, "path": media_roots.relative(r, inside)}


def _exists(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def _check(path: str) -> Future[bool]:
    """``_exists`` on a daemon thread: a stat hung on an offline share delays neither the
    response nor shutting the app down (a pool would join its threads at exit)."""
    fut: Future[bool] = Future()

    def run() -> None:
        try:
            fut.set_result(_exists(path))
        except BaseException as exc:  # pragma: no cover - _exists catches OSError
            fut.set_exception(exc)

    threading.Thread(target=run, daemon=True, name="mosaic-folder-check").start()
    return fut


def _status(svc: Services, pid: str, card: dict[str, Any] | None) -> dict[str, Any]:
    """S3/S0 status chip: Analyzing n% · Analyzed · Scanned · Not analyzed."""
    for job in svc.store.jobs(pid, True, limit=5):
        if job.kind in ("analysis", "scan", "deepen") and job.status not in JOB_TERMINAL:
            prog = svc.store.progress(job.id)
            return {
                "state": "scanning" if job.kind == "scan" else "analyzing",
                "pct": prog.pct if prog else 0,
                "job_id": job.id,
            }
    last = svc.store.jobs(pid, None, kind="analysis", limit=1)
    if card and card.get("analyzed") and last:
        return {"state": "analyzed", "mode": (last[0].params or {}).get("mode")}
    if card and card.get("clips", 0) + card.get("photos", 0) > 0:
        return {"state": "scanned"}
    return {"state": "not_analyzed"}


@router.get("/projects")
def list_projects(svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "projects.read", "*")
    rows = svc.control.projects(me)
    futures = {r.project_id: _check(r.root_path) for r in rows}
    wait(futures.values(), timeout=MISSING_CHECK_S)  # stragglers report missing: null
    items = []
    for r in sorted(rows, key=lambda r: r.last_opened_at, reverse=True):
        f = futures[r.project_id]
        missing = (not f.result()) if f.done() else None  # None: still checking (offline share)
        items.append(
            {
                "id": r.project_id,
                "name": r.name,
                "placement": r.placement,
                "fs_class": r.fs_class,
                "folder": _client_path(svc, Path(r.root_path)),
                "missing": missing,
                "last_opened_at": r.last_opened_at,
                "card": r.card,
                "status": _status(svc, r.project_id, r.card),
            }
        )
    return {"items": items, "next_cursor": None}


@router.post("/projects/preview")
def preview_folder(body: FolderRef, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """What opening this folder would do — no writes (S4)."""
    check(me, "projects.create", body.path)
    folder = _folder(svc, body)
    if not folder.is_dir():
        raise HTTPException(404, "That folder doesn't exist.")
    c = preview(folder)
    known = _known_project(svc, folder)
    return {
        "name": folder.name,
        "fs_class": c.fs_class.value,
        "reason": c.reason,
        "placement": PLACEMENT_FOR_CLASS.get(c.fs_class, Placement.IN_FOLDER).value,
        "counts": quick_counts(folder, PREVIEW_MAX_ENTRIES),
        "project_id": known,
    }


@router.post("/projects", status_code=201)
def create_project(body: CreateBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """Create the project (or open it when the folder already is one) and start a scan."""
    check(me, "projects.create", body.path)
    folder = _folder(svc, body)
    if not folder.is_dir():
        raise HTTPException(404, "That folder doesn't exist.")
    existing = _known_project(svc, folder) is not None
    try:
        if existing:  # opened as it is: a placement change belongs to S21, not to S4
            project = open_project(svc.control, me, folder)
        else:
            project = init_project(
                svc.control, me, folder, name=body.name, placement=body.placement
            )
    except PlacementRefusedError as exc:
        raise HTTPException(422, str(exc)) from None
    except NotAProjectError:
        raise HTTPException(409, "That folder's project can't be opened. Try again.") from None
    try:
        svc.leases.hold(project.id, project.outputs_dir)
        job = submit_scan(svc.executor, me, project)
        project_cards.refresh(svc.control, project)
        return {
            "id": project.id,
            "name": project.descriptor.name,
            "created": not existing,
            "placement": project.placement.value,
            "scan_job": job,
        }
    finally:
        project.close(checkpoint=False)


@router.get("/projects/{pid}/inventory")
def get_inventory(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S5: cameras, the day timeline, what needs attention and the grouping notes."""
    from mosaic.app.routers.edits import _project
    from mosaic.library.inventory_view import inventory

    check(me, "library.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return inventory(s)


@router.get("/projects/{pid}/inventory/files")
def get_inventory_files(
    pid: str,
    kind: str = Query(pattern="^(unreadable|limited|cloud)$"),
    group: int | None = None,
    after: int | None = None,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """S5 "Show files": the files behind one Needs-attention row (ADR 0040)."""
    from mosaic.app.routers.edits import _project
    from mosaic.library.inventory_view import inventory_files

    check(me, "library.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        try:
            return inventory_files(s, kind, group, after)
        except LookupError:
            raise HTTPException(404, "no such group") from None


@router.post("/projects/{pid}/cloud-files/download", status_code=202)
def download_cloud_files(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """Start downloading the project's cloud-only files, then rescan (a job)."""
    from mosaic.app.routers.edits import _project
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec

    check(me, "project.write", pid)
    with _project(svc, me, pid, write=True) as project:
        job = svc.executor.submit(
            me,
            JobSpec(
                project_id=project.id,
                kind="scan",
                params={"scan_only": True},
                tasks=[
                    TaskSpec(
                        kind="media.cloud_download",
                        stage="download",
                        resource_class=ResourceClass.IO,
                        label="downloading from the cloud",
                    )
                ],
            ),
        )
    return {"job_id": job}


@router.delete("/projects/{pid}/recent", status_code=204)
def remove_recent(pid: str, svc: Services = Svc, me: Principal = Me) -> None:
    """S3 "Remove from list": hides the project from recents (ADR 0039). Nothing is deleted:
    the footage, the project's data and its registry row stay, so opening the folder again
    brings it back with its analysis, external placement included."""
    from mosaic.storage import lease
    from mosaic.storage.models_control import ProjectRegistry

    check(me, "projects.write", pid)
    with svc.control.db.session() as s:
        row = s.get(ProjectRegistry, pid)
        if row is None or row.user_id != me.user_id:
            raise HTTPException(404, "unknown project")
        row.hidden_at = now_iso()
    folder = svc.leases.drop(pid)
    if folder is not None:
        lease.release(folder, svc.control.installation_id)
