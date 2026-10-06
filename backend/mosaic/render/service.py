"""Render services shared by the CLI and the API: create a render and submit its job."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.principal import Principal
from mosaic.jobs.executor import Executor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.media.tools import working_h264_encoders
from mosaic.render.plan import dominant_shape, profile
from mosaic.storage.models_project import Asset, EditVersion, Render
from mosaic.storage.projects import Project


def _native(s: Session, events: list[dict[str, Any]]) -> Fraction | None:
    """The display shape covering most of the edit's running time (ADR 0046)."""
    ids = {int(e["asset_id"][4:]) for e in events}
    sizes = {
        aid: (w, h)
        for aid, w, h in s.execute(
            select(Asset.id, Asset.display_width, Asset.display_height).where(Asset.id.in_(ids))
        )
    }
    return dominant_shape(
        [
            (
                *sizes.get(int(e["asset_id"][4:]), (None, None)),
                e["timeline_out"]["frames"] - e["timeline_in"]["frames"],
            )
            for e in events
        ]
    )


def create_render(
    project: Project, edit_id: int, version: int, kind: str, lossless: bool = False
) -> int:
    with project.write() as s:
        v = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == edit_id, EditVersion.version == version
            )
        )
        if v is None:
            raise LookupError(f"edt_{edit_id:04d} has no version {version}")
        req = v.request or {}
        events = v.timeline["tracks"][0]["events"]
        prof = profile(
            kind,
            list(working_h264_encoders()),
            lossless,
            aspect=req.get("aspect", "16:9"),
            resolution=req.get("resolution", "1080p"),
            native=_native(s, events),
        )
        r = Render(
            edit_id=edit_id,
            version=version,
            profile=prof.as_json(),
            status="pending",
            metrics={},
            created_at=now_iso(),
        )
        s.add(r)
        s.flush()
        return r.id


def submit_render(
    executor: Executor, principal: Principal, project: Project, render_id: int
) -> int:
    with project.db.session() as s:
        r = s.get(Render, render_id)
        assert r is not None
        v = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == r.edit_id, EditVersion.version == r.version
            )
        )
        assert v is not None
        n = len(v.timeline["tracks"][0]["events"])
        label = f"edt_{r.edit_id:04d} v{r.version} {r.profile['kind']}"
    tasks = [
        TaskSpec(
            kind="render.chunk",
            stage="render",
            resource_class=ResourceClass.GPU_ENCODE,
            params={"render_id": render_id, "index": i},
            label=f"{label} shot {i + 1}/{n}",
        )
        for i in range(n)
    ]
    tasks.append(
        TaskSpec(
            kind="render.assemble",
            stage="assemble",
            resource_class=ResourceClass.CPU,
            params={"render_id": render_id},
            label=f"{label} assemble",
            deps=list(range(n)),
        )
    )
    job_id = executor.submit(
        principal,
        JobSpec(project_id=project.id, kind="render", params={"render_id": render_id}, tasks=tasks),
    )
    with project.write() as s:
        row = s.get(Render, render_id)
        assert row is not None
        row.job_id = job_id
    return job_id


def latest_version(project: Project, edit_id: int) -> int | None:
    with project.db.session() as s:
        return s.scalar(
            select(EditVersion.version)
            .where(EditVersion.edit_id == edit_id)
            .order_by(EditVersion.version.desc())
            .limit(1)
        )


def get_render(project: Project, render_id: int) -> Render | None:
    with project.db.session() as s:
        r = s.get(Render, render_id)
        if r is not None:
            s.expunge(r)
        return r


class RenderStateError(ValueError):
    """The action does not apply to the render in its current state (HTTP 409)."""


def render_state(status: str, job_status: str | None) -> str:
    """A render's state for the screens and its actions: a pending row whose job ended
    without a result (failed, or cancelled from Activity) takes the job's end."""
    if status == "pending" and job_status in ("failed", "cancelled"):
        return job_status
    return status


def job_status(store: JobStore, job_id: int | None) -> str | None:
    job = store.job(job_id) if job_id is not None else None
    return job.status if job is not None else None


def _row(s: Session, render_id: int) -> Render:
    r = s.get(Render, render_id)
    if r is None:
        raise LookupError(f"no render {render_id}")
    return r


def cancel_render(
    executor: Executor, store: JobStore, principal: Principal, project: Project, render_id: int
) -> None:
    """Stops a queued or running render (S20 Cancel / Remove). Chunks already made stay in
    the cache, so a re-render reuses them."""
    with project.write() as s:
        r = _row(s, render_id)
        if render_state(r.status, job_status(store, r.job_id)) != "pending":
            raise RenderStateError("only a queued or running render can be cancelled")
        job_id = r.job_id
        r.status = "cancelled"
        r.finished_at = now_iso()
    if job_id is not None:
        executor.cancel(principal, job_id)


def rerender(project: Project, store: JobStore, render_id: int) -> int:
    """A new render of the same version and kind (S20 Re-render); returns its id."""
    with project.db.session() as s:
        r = _row(s, render_id)
        if render_state(r.status, job_status(store, r.job_id)) == "pending":
            raise RenderStateError("this render is still queued or running")
        edit_id, version = r.edit_id, r.version
        kind, lossless = str(r.profile["kind"]), bool(r.profile.get("lossless"))
    return create_render(project, edit_id, version, kind, lossless)


def delete_file(project: Project, render_id: int) -> None:
    """Deletes a finished render's file (a derived output, never an original); the row
    stays as history with status ``deleted``."""
    from mosaic.render.tasks import output_path

    with project.write() as s:
        r = _row(s, render_id)
        if r.status != "done":
            raise RenderStateError("only a finished render has a file to delete")
        if r.path:
            output_path(project.workspace, r).unlink(missing_ok=True)
        r.path = None
        r.status = "deleted"
