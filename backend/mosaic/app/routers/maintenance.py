"""Project storage and removal (S21) and diagnostics (S23); ADR 0051.

Clearing regenerable files runs as a job (invariant 8). Removing MosAic's data renames
its folders aside in the request (instant) and purges them in the background.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.jobs import diagnostics as diag
from mosaic.jobs.model import APP_PROJECT
from mosaic.storage import cleanup, lease

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


def _busy(svc: Services, pid: str) -> bool:
    return bool(svc.store.jobs(pid, True, limit=1))


@router.get("/projects/{pid}/storage")
def get_storage(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S21 Storage: bytes per group, regenerable or kept."""
    check(me, "project.read", pid)
    with _project(svc, me, pid) as project:
        out = cleanup.breakdown(project)
    clearing = svc.store.jobs(pid, True, kind="storage", limit=1)
    out["clearing_job_id"] = clearing[0].id if clearing else None
    return out


@router.post("/projects/{pid}/storage/clear-cache", status_code=202)
def clear_cache(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "project.write", pid)
    if _busy(svc, pid):
        raise HTTPException(409, "Wait until the running analysis or render finishes.")
    with _project(svc, me, pid, write=True) as project:
        job = svc.executor.submit(me, cleanup.clear_job(project.id))
    return {"job_id": job}


class RemoveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_name: str


@router.delete("/projects/{pid}/workspace")
def remove_workspace(
    pid: str, body: RemoveBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """S21 Danger zone: deletes MosAic's folder and descriptor; the footage stays."""
    check(me, "project.delete", pid)
    if _busy(svc, pid):
        raise HTTPException(409, "Wait until the running analysis or render finishes.")
    with _project(svc, me, pid, write=True) as project:
        if body.confirm_name.strip() != project.descriptor.name:
            raise HTTPException(422, "Type the project's name exactly to confirm.")
        folder = svc.leases.drop(pid)
        if folder is not None:
            lease.release(folder, svc.control.installation_id)
        try:
            renamed = cleanup.remove_project(svc.control, project, pid)
        except cleanup.RemovalError as exc:
            if folder is not None:  # nothing was removed: keep the project open here
                lease.acquire(folder, svc.control.installation_id)
                svc.leases.hold(pid, folder)
            raise HTTPException(409, str(exc)) from None
    cleanup.purge_in_background()
    return {"project_id": pid, "removed": True, "folders": len(renamed)}


# ------------------------------------------------------------------ diagnostics


@router.get("/diagnostics/tasks")
def diagnostics_tasks(
    project: str | None = None,
    status: str | None = None,
    cursor: int | None = None,
    limit: int = Query(diag.PAGE, ge=1, le=500),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    check(me, "diagnostics.read", project or "app")
    if status is not None and status not in diag.STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(diag.STATUSES)}")
    return diag.task_rows(svc.control, me, project, status, cursor, limit)


@router.get("/diagnostics/tasks/{tid}")
def diagnostics_task(tid: int, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "diagnostics.read", "app")
    out = diag.task_detail(svc.control, me, tid)
    if out is None:
        raise HTTPException(404, "No such task.")
    return out


@router.post("/diagnostics/tasks/{tid}/retry")
def diagnostics_retry(tid: int, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S23 Retry: this task and the tasks it cancelled run again."""
    check(me, "job.retry", str(tid))
    task = svc.store.task(tid)
    if task is None:
        raise HTTPException(404, "No such task.")
    if task.project_id != APP_PROJECT and svc.control.project_root(task.project_id) is None:
        raise HTTPException(409, "This task's project was removed from MosAic.")
    n = svc.store.retry_task(tid)
    if not n:
        raise HTTPException(
            409, "Only a failed task in a job that wasn't cancelled can be retried."
        )
    return {"task_id": tid, "reset": n}


@router.post("/diagnostics/tasks/{tid}/skip")
def diagnostics_skip(tid: int, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S23 Skip: accept a failed task; what it held back runs, and its job can finish."""
    check(me, "job.retry", str(tid))
    if svc.store.task(tid) is None:
        raise HTTPException(404, "No such task.")
    if not svc.store.skip_failed(tid, "skipped from Diagnostics"):
        raise HTTPException(409, "Only a failed task can be skipped.")
    return {"task_id": tid, "skipped": True}


@router.post("/diagnostics/bundle", response_class=Response)
def diagnostics_bundle(svc: Services = Svc, me: Principal = Me) -> Response:
    """A redacted zip for support (system, settings, recent jobs and tasks, log tails)."""
    from mosaic.app.routers.system import system_info

    check(me, "diagnostics.read", "app")
    data = diag.bundle(svc.control, me, system_info(svc, me))
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="mosaic-diagnostics.zip"'},
    )
