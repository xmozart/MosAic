"""Project lifecycle endpoints (docs/ui/API_MAP.md "Projects"; S0 and S3; ADR 0023):
open (takes the lease, or read-only), close (releases it), relink after a move."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.modes import from_params
from mosaic.core.principal import Principal, check
from mosaic.media.pipeline import submit_analysis
from mosaic.storage import lease
from mosaic.storage.descriptor import read_descriptor
from mosaic.storage.placement import Placement
from mosaic.storage.projects import (
    NotAProjectError,
    ReadOnlyProjectError,
    folder_fingerprint,
    open_project,
)

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only: bool = False
    take_over: bool = False  # only after the UI warned (S0 "Project open elsewhere")


class RelinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choose_folder: str | None = None


def _root(svc: Services, pid: str) -> Path:
    root = svc.control.project_root(pid)
    if root is None:
        raise HTTPException(404, "unknown project")
    return root


@router.post("/projects/{pid}/open")
def open_(
    pid: str, body: OpenBody | None = None, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "project.open", pid)
    body = body or OpenBody()
    try:
        project = open_project(
            svc.control, me, _root(svc, pid), read_only=body.read_only, take_over=body.take_over
        )
    except NotAProjectError as exc:
        raise HTTPException(404, str(exc)) from None
    try:
        if body.read_only:
            svc.leases.open_read_only(pid)
        else:
            svc.leases.hold(pid, project.outputs_dir)
        held = lease.read(project.outputs_dir)
        return {
            "project_id": pid,
            "read_only": body.read_only,
            "placement": project.placement.value,
            "lease": None if body.read_only or held is None else {"until": held.expires_at},
        }
    finally:
        project.close(checkpoint=False)


@router.post("/projects/{pid}/close")
def close(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "project.close", pid)
    folder = svc.leases.drop(pid)
    if folder is not None:
        lease.release(folder, svc.control.installation_id)
    return {"project_id": pid, "closed": True}


def _same_project(pid: str, folder: Path, svc: Services) -> bool:
    d = read_descriptor(folder)
    if d is not None:
        return d.project_id == pid
    row = next((r for r in svc.control.projects(svc.principal) if r.project_id == pid), None)
    return (
        row is not None
        and row.placement == Placement.EXTERNAL.value
        and row.folder_fingerprint is not None
        and folder_fingerprint(folder) == row.folder_fingerprint
    )


@router.post("/projects/{pid}/relink", status_code=202)
def relink(
    pid: str, body: RelinkBody | None = None, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """Re-scan the project's folder, or the folder it was moved to (``choose_folder``):
    files whose content fingerprint matches keep all their analysis (M1 acceptance 3)."""
    check(me, "project.write", pid)
    if pid in svc.leases.read_only:
        raise ReadOnlyProjectError(
            "this project is open read-only (it is being edited on another computer)"
        )
    body = body or RelinkBody()
    root = _root(svc, pid)
    if body.choose_folder:
        chosen = Path(body.choose_folder).expanduser().resolve()
        if not chosen.is_dir():
            raise HTTPException(422, f"not a folder: {chosen}")
        if not _same_project(pid, chosen, svc):
            raise HTTPException(422, "that folder does not hold this project's footage")
        root = chosen
    elif not root.is_dir():
        raise HTTPException(409, f"the project folder is missing: {root}; choose where it is")
    project = open_project(svc.control, me, root)  # registers the (new) root
    try:
        # The mode of the last analysis, so nothing is recomputed at another density.
        last = svc.store.jobs(pid, None, kind="analysis", limit=1)
        analysis = last[0] if last else None
        mode = from_params(analysis.params if analysis else None)
        job = submit_analysis(svc.executor, me, project, mode)
    finally:
        project.close(checkpoint=False)
    return {"job_id": job, "root": str(root), "mode": mode.name}
