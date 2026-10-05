"""Trip context endpoints (docs/ui/API_MAP.md, S7): read, replace, parse free text.

Parsing is AI work, so it runs as a job (invariant 8); the job's result holds the proposed
structure, which the client shows for confirmation and then PUTs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.library.context import TripContext, load, revision, save
from mosaic.library.summaries import submit_summaries
from mosaic.storage.models_project import Summary

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


class ParseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20000)


@router.get("/projects/{pid}/trip-context")
def get_context(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "context.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return {"revision": revision(s), **load(s).model_dump(mode="json")}


@router.put("/projects/{pid}/trip-context")
def put_context(
    pid: str, body: dict[str, Any], svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "context.write", pid)
    body = {k: v for k, v in body.items() if k not in ("revision", "summaries_job")}
    try:
        ctx = TripContext.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        ) from None
    with _project(svc, me, pid) as project:
        with project.write() as s:
            rev = save(s, ctx, "user")
        # A context change re-runs summaries only (PRODUCT.md §3, S7).
        job = submit_summaries(svc.executor, me, project)
    return {"revision": rev, "summaries_job": job, **ctx.model_dump(mode="json")}


@router.post("/projects/{pid}/trip-context/parse", status_code=202)
def parse_context(
    pid: str, body: ParseBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "context.write", pid)
    with _project(svc, me, pid) as project:
        job_id = svc.executor.submit(
            me,
            JobSpec(
                project_id=project.id,
                kind="context",
                tasks=[
                    TaskSpec(
                        kind="context.parse",
                        stage="context",
                        resource_class=ResourceClass.AI_API,
                        params={"text": body.text},
                        label="reading the trip notes",
                    )
                ],
            ),
        )
    return {"job_id": job_id}


@router.get("/projects/{pid}/summaries")
def get_summaries(
    pid: str,
    level: str = "day",
    after_ref: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """Trip and day summaries (``level=day``), or one level: trip, day, scene, shot.
    Scene and shot summaries are paged by ``ref`` (``after_ref``, ``limit``)."""
    check(me, "context.read", pid)
    if level not in ("trip", "day", "scene", "shot"):
        raise HTTPException(422, "level must be trip, day, scene or shot")
    levels = ["trip", "day"] if level == "day" else [level]
    q = select(Summary).where(Summary.level.in_(levels)).order_by(Summary.level, Summary.ref)
    paged = level in ("scene", "shot")
    if paged:
        if after_ref is not None:
            q = q.where(Summary.ref > after_ref)
        q = q.limit(limit + 1)
    with _project(svc, me, pid) as project, project.db.session() as s:
        rows = list(s.scalars(q))
        more = paged and len(rows) > limit
        rows = rows[:limit] if paged else rows
        return {
            "items": [{"level": r.level, "ref": r.ref, "text": r.text, **r.data} for r in rows],
            "next_after_ref": rows[-1].ref if more else None,
        }
