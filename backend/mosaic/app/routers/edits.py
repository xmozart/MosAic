"""Edit and render endpoints (docs/ui/API_MAP.md "Edits", "Renders"; M2 basic, ADR 0047).

``{eid}`` is the edit's ULID, resolved to its project through the control DB's edit
index. Generation runs as a job (invariant 8): handlers only create or query.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from sqlalchemy import select

from mosaic.ai.registry import embedder
from mosaic.app.auth import server_mode
from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.editing import draft as draft_ops
from mosaic.editing import estimate as edit_estimate
from mosaic.editing import presets
from mosaic.editing.cards import PAGE, edit_cards, render_rows, version_facts
from mosaic.editing.generate import version_json
from mosaic.editing.music import MusicPathError
from mosaic.editing.music import check_path as check_music_path
from mosaic.editing.request import STORY_PRESETS, Category, EditRequest
from mosaic.editing.service import (
    EditNotFoundError,
    create_edit,
    edit_ref,
    get_version,
    report,
    resolve_edit,
    submit_generate,
)
from mosaic.render.plan import Codec
from mosaic.storage import media_roots
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
        project = open_project(svc.control, me, root, read_only=read_only, move=False)
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


@router.get("/projects/{pid}/edit-categories")
def edit_categories(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S14 step 3: the content categories, most frequent in this library first, each with
    its clip count (ADR 0072). The wizard shows the first six; More categories the rest."""
    from mosaic.editing.categories import library_counts

    check(me, "edits.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return {"items": library_counts(s)}


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


def _music(svc: Services, request: EditRequest) -> EditRequest:
    """The music track must be a readable file (ADR 0080); a server reads files inside its
    media roots only (ADR 0035), and stores the canonical path."""
    if request.music is None:
        return request
    path = request.music.path
    if server_mode():
        try:
            _, canonical = media_roots.confine(svc.control, path)
        except media_roots.PathRefusedError as exc:
            raise HTTPException(403, str(exc)) from None
        path = str(canonical)
    try:
        check_music_path(path)
    except MusicPathError as exc:
        raise HTTPException(422, str(exc)) from None
    music = request.music.model_copy(update={"path": path})
    return request.model_copy(update={"music": music})


@router.post("/projects/{pid}/edits", status_code=202)
def create_and_generate(
    pid: str, body: dict[str, Any], svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "edits.write", pid)
    request = _music(svc, _request(body.get("request", body)))
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
    """The latest version, and whether its draft has unsaved changes (``draft``)."""
    from mosaic.editing import draft

    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        out = _version(svc, project, edit_id, None)
        with project.db.session() as s:
            d = draft.load(s, edit_id)
            out["draft"] = {
                "base_version": d.base.version,
                "dirty": d.dirty,
                "ops": len(d.ops),
                "can_undo": d.can_undo,
                "can_redo": d.can_redo,
            }
        return out


# ------------------------------------------------------------------------- draft


class DraftOpBody(BaseModel):
    """One storyboard change (ADR 0067): ``move_shot``, ``move_beat``, ``remove_shot``,
    ``lock_shot`` or ``replace_shot``."""

    model_config = ConfigDict(extra="forbid")

    op: draft_ops.Op


def _draft_change(
    svc: Services, me: Principal, eid: str, action: str, op: Any = None
) -> dict[str, Any]:
    from mosaic.editing import draft
    from mosaic.editing.service import change_draft, draft_state

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            change_draft(project, edit_id, action, op)
        except draft.DraftError as exc:
            raise HTTPException(422, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        return draft_state(project, edit_id)


@router.get("/edits/{eid}/draft")
def get_draft(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S16's storyboard: the draft's beats and shots, undo state and current timing."""
    from mosaic.editing.service import draft_state

    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        try:
            out = draft_state(project, edit_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        # S16's "regenerating" state, from the jobs still running (so a reload keeps it):
        # the beats being regenerated, and the story or edit as a whole (ADR 0069, 0070).
        running = [
            j.params
            for j in svc.store.jobs(project.id, True, kind="edit")
            if j.params.get("edit_id") == edit_id
        ]
        out["regenerating"] = sorted(
            {str(p["beat_id"]) for p in running if "beat_id" in p}
            | {str(b) for p in running for b in p.get("beat_ids", [])}
        )
        out["regenerating_scope"] = next((p["scope"] for p in running if "scope" in p), None)
        return out


@router.post("/edits/{eid}/draft/ops")
def add_draft_op(
    eid: str, body: DraftOpBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    return _draft_change(svc, me, eid, "op", body.op)


@router.post("/edits/{eid}/draft/undo")
def undo_draft(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    return _draft_change(svc, me, eid, "undo")


@router.post("/edits/{eid}/draft/redo")
def redo_draft(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    return _draft_change(svc, me, eid, "redo")


@router.post("/edits/{eid}/regenerate", status_code=202)
def regenerate_edit(
    eid: str,
    scope: str = Query(..., pattern="^(story|all|opening|ending)$"),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """Regenerate the story (new beats from the edit's own clips) or the whole edit
    (ADR 0070), or give it a stronger opening or a different ending (its first or last
    beat; ADR 0074); the owner's locked shots stay."""
    from mosaic.editing.service import submit_end, submit_regenerate

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            if scope in ("opening", "ending"):
                return {"job_id": submit_end(svc.executor, me, project, edit_id, scope)}
            return {"job_id": submit_regenerate(svc.executor, me, project, edit_id, scope)}
        except draft_ops.UnknownBeatError as exc:
            raise HTTPException(404, str(exc)) from None
        except draft_ops.DraftError as exc:
            raise HTTPException(422, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None


class CategoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    more: StrictBool


@router.post("/edits/{eid}/category", status_code=202)
def more_or_less_category(
    eid: str, body: CategoryBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """More or less of a content category: its weight moves one step and the edit is
    regenerated with the owner's locks kept (ADR 0074). 409 at the end of the scale."""
    from mosaic.editing.service import more_or_less

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            job, weight = more_or_less(svc.executor, me, project, edit_id, body.category, body.more)
        except draft_ops.DraftError as exc:
            raise HTTPException(409, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        return {"job_id": job, "category": body.category, "weight": weight}


@router.post("/edits/{eid}/beats/{bid}/regenerate", status_code=202)
def regenerate_beat(eid: str, bid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """A fresh take on one beat; its locked shots keep their cut and slot (ADR 0069)."""
    from mosaic.editing.service import submit_regenerate_beat

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            return {"job_id": submit_regenerate_beat(svc.executor, me, project, edit_id, bid)}
        except draft_ops.UnknownBeatError as exc:
            raise HTTPException(404, str(exc)) from None
        except draft_ops.DraftError as exc:
            raise HTTPException(422, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None


class DurationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_s: StrictInt  # bounds: draft_ops.SetDuration's


@router.post("/edits/{eid}/duration", status_code=201)
def change_duration(
    eid: str, body: DurationBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """ "Make it N seconds": a new version re-timed to that length, with no AI call
    (M4 acceptance 3; ADR 0071). 409 when the length is already that."""
    from mosaic.editing.draft import DraftChangedError
    from mosaic.editing.service import set_duration

    check(me, "edits.write", eid)
    try:
        draft_ops.SetDuration(duration_s=body.duration_s)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False)) from None
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            number = set_duration(project, edit_id, body.duration_s)
        except DraftChangedError as exc:
            raise HTTPException(409, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        if number is None:
            raise HTTPException(409, f"the edit is already {body.duration_s} s")
        return _version(svc, project, edit_id, number)


@router.get("/edits/{eid}/shots/{shot}/alternatives")
def shot_alternatives(
    eid: str, shot: str, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """S16's ShotPopover: what this shot can be replaced with (``replace_shot``)."""
    from mosaic.editing.service import alternatives

    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        try:
            items, locked = alternatives(project, edit_id, shot)
            return {"items": items, "locked": locked}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except draft_ops.DraftError as exc:
            raise HTTPException(404, str(exc)) from None


@router.post("/edits/{eid}/versions", status_code=201)
def save_version(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """Save the draft as a new version (S16 "Save version"); 409 when it has no changes."""
    from mosaic.editing.draft import DraftChangedError
    from mosaic.editing.service import save_draft
    from mosaic.render.service import latest_version

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            number = save_draft(project, edit_id)
        except DraftChangedError as exc:
            raise HTTPException(409, str(exc)) from None
        if number is None:
            if latest_version(project, edit_id) is None:
                raise HTTPException(404, "this edit has no versions yet")
            raise HTTPException(409, "the draft has no changes to save")
        return _version(svc, project, edit_id, number)


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
    svc: Services,
    me: Principal,
    eid: str,
    version: int | None,
    kind: str,
    *,
    codec: Codec = "h264",
    resolution: str | None = None,
    loudness: str | None = None,
    sidecars: tuple[str, ...] = (),
) -> dict[str, Any]:
    from mosaic.editing.draft import DraftChangedError
    from mosaic.editing.service import draft_dirty
    from mosaic.render.service import create_render, submit_render, version_to_render

    with _edit(svc, me, eid, write=True) as (project, edit_id):
        if version is None and draft_dirty(project, edit_id):
            check(me, "edits.write", eid)  # rendering the draft saves it as a version
        try:
            v = version_to_render(project, edit_id, version)
        except DraftChangedError as exc:
            raise HTTPException(409, str(exc)) from None
        if v is None:
            raise HTTPException(404, "this edit has no versions yet")
        try:
            rid = create_render(
                project,
                edit_id,
                v,
                kind,
                codec=codec,
                resolution=resolution,
                loudness=loudness,
                sidecars=sidecars,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except RuntimeError as exc:  # no encoder for the codec works here (ADR 0084)
            raise HTTPException(422, str(exc)) from None
        job_id = submit_render(svc.executor, me, project, rid)
        return {"project_id": project.id, "render_id": rid, "version": v, "job_id": job_id}


@router.post("/edits/{eid}/preview", status_code=202)
def preview(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "renders.write", eid)
    return _start_render(svc, me, eid, None, "preview")


class RenderBody(BaseModel):
    """``POST /renders``: a 720p preview from proxies, or a final from the originals
    (``final``) in S19's preset ``codec`` at ``resolution`` (else the edit's), with the
    ``sidecars`` asked for (ADR 0084)."""

    model_config = ConfigDict(extra="forbid")

    edit_id: str
    version: StrictInt | None = None
    final: StrictBool = False
    codec: Literal["h264", "hevc", "prores"] = "h264"
    resolution: Literal["720p", "1080p", "1440p", "4k"] | None = None
    loudness: Literal["web", "tv"] | None = None  # else the edit's request
    sidecars: list[Literal["edl", "srt", "report"]] = Field(default_factory=list)


@router.post("/renders", status_code=202)
def start_render(body: RenderBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "renders.write", body.edit_id)
    if not body.final:
        return _start_render(svc, me, body.edit_id, body.version, "preview")
    return _start_render(
        svc,
        me,
        body.edit_id,
        body.version,
        "final",
        codec=body.codec,
        resolution=body.resolution,
        loudness=body.loudness,
        sidecars=tuple(body.sidecars),
    )


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
    pid: str,
    rid: int,
    download: bool = False,
    part: Literal["video", "edl", "srt", "report"] = "video",
    svc: Services = Svc,
    me: Principal = Me,
) -> Response:
    """The rendered video, with Range requests (S17's player; S20 Open and Download), or
    one of its sidecars: the EDL JSON, SRT captions or selection report (ADR 0084)."""
    from mosaic.render.service import get_render
    from mosaic.render.tasks import output_path, sidecar_path

    check(me, "renders.read", pid)
    with _project(svc, me, pid) as project:
        r = get_render(project, rid)
        path = output_path(project.workspace, r) if r is not None and r.path else None
    if path is not None and part != "video":
        path = sidecar_path(path, part)
    if r is None or path is None or not path.is_file():
        raise HTTPException(404, "No rendered file." if part == "video" else f"No {part} file.")
    media = {
        ".mov": "video/quicktime",
        ".mp4": "video/mp4",
        ".json": "application/json",
        ".srt": "application/x-subrip",
        ".txt": "text/plain; charset=utf-8",
    }[path.suffix]
    return FileResponse(
        path,
        media_type=media,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


# ------------------------------------------------------------------- findings (S17)


@router.get("/edits/{eid}/findings")
def list_findings(
    eid: str, version: int | None = None, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """A version's critic findings (the latest version's by default) with their status
    (ADR 0081)."""
    from mosaic.editing import draft, findings

    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id), project.db.session() as s:
        if version is None:
            latest = draft.latest(s, edit_id)
            if latest is None:
                raise HTTPException(404, "this edit has no version yet")
            version = latest.version
        items = [
            findings.as_json(f, findings.fix_text(s, f.ops))
            for f in findings.of_version(s, edit_id, version)
        ]
        applied = [
            findings.as_json(f, findings.fix_text(s, f.ops))
            for f in findings.applied_in(s, edit_id, version)
        ]
        return {"version": version, "items": items, "applied": applied}


def _apply_findings(svc: Services, me: Principal, eid: str, which: list[str] | None) -> Any:
    from mosaic.editing import draft, findings

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        if which is None:  # apply all: every open finding with a fix on the latest version
            with project.db.session() as s:
                latest = draft.latest(s, edit_id)
                if latest is None:
                    raise HTTPException(404, "this edit has no version yet")
                rows = findings.of_version(s, edit_id, latest.version)
                which = [f.uid for f in rows if f.status == "open" and f.ops]
            if not which:
                raise HTTPException(422, "None of these findings can be applied now.")
        try:
            number, skipped = findings.apply(project, edit_id, which)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except findings.FindingStateError as exc:
            raise HTTPException(409, str(exc)) from None
        except findings.FindingError as exc:
            raise HTTPException(422, str(exc)) from None
        out = _version(svc, project, edit_id, number)
        out["skipped_findings"] = skipped
        return out


@router.post("/edits/{eid}/findings/{fid}/apply", status_code=201)
def apply_finding(eid: str, fid: str, svc: Services = Svc, me: Principal = Me) -> Any:
    """Apply one finding: a child version with its fix (ADR 0081)."""
    return _apply_findings(svc, me, eid, [fid])


@router.post("/edits/{eid}/findings/apply-all", status_code=201)
def apply_all_findings(eid: str, svc: Services = Svc, me: Principal = Me) -> Any:
    """Apply every open finding that has a fix: one child version."""
    return _apply_findings(svc, me, eid, None)


@router.post("/edits/{eid}/findings/regenerate", status_code=202)
def regenerate_with_fixes(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """S17 "Regenerate with fixes": the fixes applied, then the beats with issues that
    have no fix regenerated as one job (ADR 0089). 409 with unsaved storyboard changes,
    422 when there is nothing to do."""
    from mosaic.editing import findings
    from mosaic.editing.service import submit_fixes

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            return submit_fixes(svc.executor, me, project, edit_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except findings.FindingStateError as exc:
            raise HTTPException(409, str(exc)) from None
        except findings.FindingError as exc:
            raise HTTPException(422, str(exc)) from None


def _ignore(svc: Services, me: Principal, eid: str, fid: str | None) -> dict[str, Any]:
    from mosaic.editing import draft, findings

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        uids = [fid] if fid else []
        if fid is None:
            with project.db.session() as s:
                latest = draft.latest(s, edit_id)
                rows = findings.of_version(s, edit_id, latest.version) if latest else []
                uids = [f.uid for f in rows if f.status == "open"]
        try:
            return {"ignored": findings.ignore(project, edit_id, uids) if uids else 0}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None


@router.post("/edits/{eid}/findings/{fid}/ignore")
def ignore_finding(eid: str, fid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    return _ignore(svc, me, eid, fid)


@router.post("/edits/{eid}/findings/ignore-all")
def ignore_all_findings(eid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    return _ignore(svc, me, eid, None)


# --------------------------------------------------------------- versions (S18)


class RevertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


@router.post("/edits/{eid}/revert", status_code=201)
def revert_version(
    eid: str, body: RevertBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """A new version equal to ``version`` (never a destructive change; ADR 0083): its
    render reuses the earlier one's chunks. 409 when it is the latest already."""
    from mosaic.editing import versions

    check(me, "edits.write", eid)
    with _edit(svc, me, eid, write=True) as (project, edit_id):
        try:
            number = versions.revert(project, edit_id, body.version)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except versions.RevertError as exc:
            raise HTTPException(409, str(exc)) from None
        return _version(svc, project, edit_id, number)


@router.get("/edits/{eid}/compare")
def compare_versions(
    eid: str, a: int, b: int, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """S18's "What changed": the shot-level differences from version ``a`` to ``b``."""
    from mosaic.editing import versions

    check(me, "edits.read", eid)
    with _edit(svc, me, eid) as (project, edit_id):
        try:
            return versions.compare(project, edit_id, a, b)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None


# ------------------------------------------------------------- music (S14 step 5)


class TrackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)


WAVE_BARS = 48


class TrackCard(BaseModel):
    name: str
    duration_ms: int  # display only
    sample_rate: int
    peaks: list[int]


MAX_TRACK_S = 30 * 60  # longer tracks are read for their first half hour only


@router.post("/music/probe", response_model=TrackCard)
def probe_track(body: TrackBody, svc: Services = Svc, me: Principal = Me) -> TrackCard:
    """S14 step 5's track card (ADR 0086): the track's name, length, sample rate and a
    coarse waveform (``WAVE_BARS`` peaks, 0-100). The same path checks as an edit's
    music (ADR 0080); the file is only read, its first half hour at most, so the request
    stays short. A file that isn't readable audio is refused in plain words (422)."""
    import json
    import subprocess
    from fractions import Fraction

    import numpy as np

    from mosaic.media.ffmpeg.builders import audio_pcm, ffprobe_json
    from mosaic.media.ffmpeg.run import FFmpegError, run
    from mosaic.media.tools import media_tools

    check(me, "edits.write", "*")
    request = _music(
        svc, EditRequest.model_validate({"duration_s": 60, "music": {"path": body.path}})
    )
    assert request.music is not None
    path = Path(request.music.path)
    unreadable = HTTPException(422, f"{path.name}: it can't be read as audio")
    binaries, _ = media_tools()
    try:
        probe = json.loads(run(binaries, ffprobe_json(path), timeout=30).stdout)
        audio = next(
            (st for st in probe.get("streams", []) if st.get("codec_type") == "audio"), None
        )
        if audio is None:
            raise HTTPException(422, f"{path.name}: it has no audio")
        seconds = float(probe.get("format", {}).get("duration") or audio.get("duration") or 0)
        # 400 samples a second, mono: a few hundred kilobytes for half an hour.
        raw = run(
            binaries, audio_pcm(path, 400, 1, duration=Fraction(MAX_TRACK_S)), timeout=60
        ).stdout
    except (FFmpegError, subprocess.TimeoutExpired, ValueError):
        raise unreadable from None
    pcm = np.abs(np.frombuffer(raw, dtype="<f4"))
    peaks = [0] * WAVE_BARS
    if pcm.size:
        bars = np.array_split(pcm, WAVE_BARS)
        top = max(float(pcm.max()), 1e-6)
        peaks = [round(100 * float(b.max()) / top) if b.size else 0 for b in bars]
    return TrackCard(
        name=path.name,
        duration_ms=round(seconds * 1000),
        sample_rate=int(audio.get("sample_rate") or 0),
        peaks=peaks,
    )
