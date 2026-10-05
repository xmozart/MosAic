"""Edit endpoints (docs/ui/API_MAP.md "Edits", M0 subset): create, generate, read, report.

``{eid}`` is the edit's ULID, resolved to its project through the control DB's edit
index. Generation runs as a job (invariant 8): handlers only create or query.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
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
from mosaic.storage.projects import NotAProjectError, Project, open_project

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


@contextmanager
def _project(svc: Services, me: Principal, pid: str) -> Iterator[Project]:
    root = svc.control.project_root(pid)
    if root is None:
        raise HTTPException(404, "unknown project")
    try:
        project = open_project(svc.control, me, root)
    except NotAProjectError as exc:
        raise HTTPException(404, str(exc)) from None
    try:
        yield project
    finally:
        project.close()


@contextmanager
def _edit(svc: Services, me: Principal, eid: str) -> Iterator[tuple[Project, int]]:
    pid = svc.control.project_for_edit(eid.upper())
    if pid is None:
        raise HTTPException(404, "unknown edit")
    with _project(svc, me, pid) as project:
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
    with _project(svc, me, pid) as project:
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
    with _edit(svc, me, eid) as (project, edit_id):
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
