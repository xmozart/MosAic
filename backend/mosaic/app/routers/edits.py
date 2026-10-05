"""Edit endpoints (docs/ui/API_MAP.md "Edits", M0 subset): create, generate, read, report.

``{eid}`` is the edit's ULID, resolved to its project through the control DB's edit
index. Generation runs as a job (invariant 8): handlers only create or query.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError
from sqlalchemy import select

from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.editing.generate import version_json
from mosaic.editing.request import EditRequest
from mosaic.editing.service import (
    EditNotFoundError,
    create_edit,
    edit_ref,
    get_version,
    report,
    resolve_edit,
    submit_generate,
)
from mosaic.storage.models_project import Edit, EditVersion
from mosaic.storage.projects import (
    NotAProjectError,
    Project,
    ReadOnlyProjectError,
    open_project,
)

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


@contextmanager
def _project(svc: Services, me: Principal, pid: str, *, write: bool = False) -> Iterator[Project]:
    """A request-scoped project handle (ADR 0023). ``write`` routes (writes, job
    submissions) need edit access: refused (409) when the app opened the project read-only
    or lost its lease; otherwise they take or renew the lease. Read routes open read-only
    unless the app holds the lease, so a read never takes it."""
    root = svc.control.project_root(pid)
    if root is None:
        raise HTTPException(404, "unknown project")
    if write and pid in svc.leases.read_only:
        raise ReadOnlyProjectError(
            "this project is open read-only (it is being edited on another computer)"
        )
    read_only = not write and pid not in svc.leases.held
    try:
        project = open_project(svc.control, me, root, read_only=read_only)
    except NotAProjectError as exc:
        raise HTTPException(404, str(exc)) from None
    try:
        yield project
    finally:
        # Request-scoped: snapshots follow stages and edit commits, not every request.
        project.close(checkpoint=False)


@contextmanager
def _edit(
    svc: Services, me: Principal, eid: str, *, write: bool = False
) -> Iterator[tuple[Project, int]]:
    pid = svc.control.project_for_edit(eid.upper())
    if pid is None:
        raise HTTPException(404, "unknown edit")
    with _project(svc, me, pid, write=write) as project:
        try:
            yield project, resolve_edit(project, eid)
        except EditNotFoundError as exc:
            raise HTTPException(404, str(exc)) from None


def _edit_json(e: Edit, latest: int | None) -> dict[str, Any]:
    return {
        "edit_id": e.uid,
        "display_id": edit_ref(e.id),
        "name": e.name,
        "request": e.request,
        "latest_version": latest,
        "created_at": e.created_at,
    }


@router.get("/projects/{pid}/edits")
def list_edits(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "edits.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        items = []
        for e in s.scalars(select(Edit).order_by(Edit.id.desc())):
            latest = s.scalar(
                select(EditVersion.version)
                .where(EditVersion.edit_id == e.id)
                .order_by(EditVersion.version.desc())
                .limit(1)
            )
            items.append(_edit_json(e, latest))
    return {"items": items, "next_cursor": None}


@router.post("/projects/{pid}/edits", status_code=202)
def create_and_generate(
    pid: str, body: dict[str, Any], svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "edits.write", pid)
    try:
        request = EditRequest.model_validate(body.get("request", body))
    except ValidationError as exc:
        raise HTTPException(
            422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        ) from None
    with _project(svc, me, pid, write=True) as project:
        edit_id = create_edit(project, request, svc.control, me, body.get("name"))
        job_id = submit_generate(svc.executor, me, project, edit_id)
        with project.db.session() as s:
            row = s.get(Edit, edit_id)
            assert row is not None
            uid = row.uid
    return {"edit_id": uid, "job_id": job_id}


@router.post("/edits/{eid}/generate", status_code=202)
def generate(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        return {"job_id": submit_generate(svc.executor, me, project, edit_id)}


@router.get("/edits/{eid}")
def get_edit(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """M0 has no draft yet: the current state is the latest version."""
    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        return _version(project, edit_id, None)


def _version(project: Project, edit_id: int, version: int | None) -> dict[str, Any]:
    try:
        v = get_version(project, edit_id, version)
    except EditNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    with project.db.session() as s:
        e = s.get(Edit, edit_id)
        assert e is not None
        out = version_json(e, v)
        out["edit_id"] = e.uid
        out["display_id"] = edit_ref(e.id)
    return out


@router.get("/edits/{eid}/versions")
def list_versions(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id), project.db.session() as s:
        rows = s.scalars(
            select(EditVersion).where(EditVersion.edit_id == edit_id).order_by(EditVersion.version)
        )
        items = [
            {
                "version": v.version,
                "created_at": v.created_at,
                "duration": v.timeline.get("duration"),
                "blocking_ok": v.metrics.get("blocking_ok"),
            }
            for v in rows
        ]
    return {"items": items, "next_cursor": None}


@router.get("/edits/{eid}/versions/{version}")
def get_edit_version(
    eid: str, version: int, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        return _version(project, edit_id, version)


@router.get("/edits/{eid}/report")
def get_report(
    eid: str,
    version: int | None = None,
    rejected_offset: int = 0,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        try:
            return report(project, edit_id, version, max(0, rejected_offset))
        except EditNotFoundError as exc:
            raise HTTPException(404, str(exc)) from None


# ----------------------------------------------------------------------- renders


def _start_render(
    svc: Services, me: Principal, eid: str, version: int | None, kind: str
) -> dict[str, Any]:
    from mosaic.render.service import create_render, latest_version, submit_render

    with _edit(svc, me, eid, write=True) as (project, edit_id):
        v = version or latest_version(project, edit_id)
        if v is None:
            raise HTTPException(404, "this edit has no versions yet")
        try:
            rid = create_render(project, edit_id, v, kind)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        job_id = submit_render(svc.executor, me, project, rid)
        return {"project_id": project.id, "render_id": rid, "version": v, "job_id": job_id}


@router.post("/edits/{eid}/preview", status_code=202)
def preview(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "renders.write", eid)
    return _start_render(svc, me, eid, None, "preview")


class RenderBody(BaseModel):
    """M0 subset of ``POST /renders``. ``final`` stands in for S19's preset/resolution
    (1080p SDR final from originals, or a 720p preview from proxies)."""

    model_config = ConfigDict(extra="forbid")

    edit_id: str
    version: StrictInt | None = None
    final: StrictBool = False


@router.post("/renders", status_code=202)
def start_render(body: RenderBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "renders.write", body.edit_id)
    return _start_render(svc, me, body.edit_id, body.version, "final" if body.final else "preview")


@router.get("/projects/{pid}/renders")
def list_renders(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    from mosaic.render.tasks import output_path
    from mosaic.storage.models_project import Render

    check(me, "renders.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        items = []
        for r in s.scalars(select(Render).order_by(Render.id.desc())):
            e = s.get(Edit, r.edit_id)
            status = r.status
            if status == "pending" and r.job_id is not None:
                job = svc.store.job(r.job_id)
                if job is not None and job.status in ("failed", "cancelled"):
                    status = job.status  # the job ended without a result
            items.append(
                {
                    "render_id": r.id,
                    "edit_id": e.uid if e else None,
                    "version": r.version,
                    "kind": r.profile.get("kind"),
                    "status": status,
                    "job_id": r.job_id,
                    "path": str(output_path(project.workspace, r)) if r.path else None,
                    "metrics": r.metrics,
                    "created_at": r.created_at,
                }
            )
    return {"items": items, "next_cursor": None}
