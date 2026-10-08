"""Edit and render endpoints (docs/ui/API_MAP.md "Edits", "Renders"; M2 basic, ADR 0047).

``{eid}`` is the edit's ULID, resolved to its project through the control DB's edit
index. Generation runs as a job (invariant 8): handlers only create or query.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError
from sqlalchemy import select

from mosaic.ai.registry import embedder
from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.editing import estimate as edit_estimate
from mosaic.editing import presets
from mosaic.editing.cards import PAGE, edit_cards, render_rows, version_facts
from mosaic.editing.generate import version_json
from mosaic.editing.request import STORY_PRESETS, EditRequest
from mosaic.editing.service import (
    EditNotFoundError,
    create_edit,
    edit_ref,
    get_version,
    report,
    resolve_edit,
    submit_generate,
)
from mosaic.storage.config import ConfigService
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
def list_edits(
    pid: str,
    cursor: int | None = None,
    limit: int = Query(PAGE, ge=1, le=200),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """S13's edit cards (ADR 0047): status, cover, format, versions, preliminary."""
    check(me, "edits.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return edit_cards(s, svc.store, project.id, cursor, limit)


@router.get("/projects/{pid}/presets")
def list_presets(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "edits.read", pid)
    if svc.control.project_root(pid) is None:
        raise HTTPException(404, "unknown project")
    return {"items": presets.cards()}


@router.get("/projects/{pid}/presets/{preset}/collage")
def preset_collage(
    pid: str, preset: str, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """Frames of the owner's own clips that suit the story (S14 StoryPresetCard)."""
    check(me, "edits.read", pid)
    if preset not in STORY_PRESETS:
        raise HTTPException(404, "unknown story preset")
    emb = embedder(ConfigService(svc.control), me)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return {"preset": preset, "frames": presets.collage(s, emb, preset)}


class EstimateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    request: dict[str, Any]


@router.post("/edits/estimate")
def estimate_edit(body: EstimateBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S14's estimate: time and AI cost of creating this edit now (ADR 0047). Reads only."""
    check(me, "edits.read", body.project_id)
    request = _request(body.request)
    running = svc.store.jobs(body.project_id, True, kind="analysis", limit=1)
    progress = svc.store.progress(running[0].id) if running else None
    with _project(svc, me, body.project_id) as project, project.db.session() as s:
        return edit_estimate.for_request(
            s,
            ConfigService(svc.control),
            me,
            project.id,
            request,
            progress.pct if progress else (0 if running else None),
        )


def _request(raw: dict[str, Any]) -> EditRequest:
    try:
        return EditRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        ) from None


@router.post("/projects/{pid}/edits", status_code=202)
def create_and_generate(
    pid: str, body: dict[str, Any], svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "edits.write", pid)
    request = _request(body.get("request", body))
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
        return _version(svc, project, edit_id, None)


def _version(svc: Services, project: Project, edit_id: int, version: int | None) -> dict[str, Any]:
    """The version, with S17's facts and its renders (newest first; ADR 0049)."""
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
        out["facts"] = version_facts(s, v)
        out["renders"] = render_rows(
            s, svc.store, project.workspace, limit=20, edit_id=edit_id, version=v.version
        )["items"]
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
        return _version(svc, project, edit_id, version)


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
def list_renders(
    pid: str,
    cursor: int | None = None,
    limit: int = Query(PAGE, ge=1, le=200),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """S20's rows: label, status with percent, size, time, error (ADR 0047)."""
    check(me, "renders.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return render_rows(s, svc.store, project.workspace, cursor, limit)


# Render ids are numbered per project, so render actions live under the project.


@router.post("/projects/{pid}/renders/{rid}/{action}", status_code=202)
def render_action(
    pid: str, rid: int, action: str, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    from mosaic.render import service as rs

    check(me, "renders.write", pid)
    if action not in ("cancel", "rerender"):
        raise HTTPException(404, "unknown action")
    with _project(svc, me, pid, write=True) as project:
        try:
            if action == "cancel":
                rs.cancel_render(svc.executor, svc.store, me, project, rid)
                return {"render_id": rid}
            new = rs.rerender(project, svc.store, rid)
            return {"render_id": new, "job_id": rs.submit_render(svc.executor, me, project, new)}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except rs.RenderStateError as exc:
            raise HTTPException(409, str(exc)) from None


@router.delete("/projects/{pid}/renders/{rid}/file")
def delete_render_file(
    pid: str, rid: int, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    from mosaic.render import service as rs

    check(me, "renders.write", pid)
    with _project(svc, me, pid, write=True) as project:
        try:
            rs.delete_file(project, rid)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except rs.RenderStateError as exc:
            raise HTTPException(409, str(exc)) from None
    return {"render_id": rid, "status": "deleted"}


@router.get("/projects/{pid}/renders/{rid}/file", response_class=Response)
def render_file(
    pid: str, rid: int, download: bool = False, svc: Services = Svc, me: Principal = Me
) -> Response:
    """The rendered video, with Range requests (S17's player; S20 Open and Download)."""
    from mosaic.render.service import get_render
    from mosaic.render.tasks import output_path

    check(me, "renders.read", pid)
    with _project(svc, me, pid) as project:
        r = get_render(project, rid)
        path = output_path(project.workspace, r) if r is not None and r.path else None
    if r is None or path is None or not path.is_file():
        raise HTTPException(404, "No rendered file.")
    media = "video/quicktime" if path.suffix == ".mov" else "video/mp4"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )
