"""Render services shared by the CLI and the API: create a render and submit its job."""

from __future__ import annotations

from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.core.principal import Principal
from mosaic.jobs.executor import Executor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.media.tools import working_h264_encoders
from mosaic.render.plan import profile
from mosaic.storage.models_project import EditVersion, Render
from mosaic.storage.projects import Project


def create_render(
    project: Project, edit_id: int, version: int, kind: str, lossless: bool = False
) -> int:
    prof = profile(kind, list(working_h264_encoders()), lossless)
    with project.write() as s:
        v = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == edit_id, EditVersion.version == version
            )
        )
        if v is None:
            raise LookupError(f"edt_{edit_id:04d} has no version {version}")
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
