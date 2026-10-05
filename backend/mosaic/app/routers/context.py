"""Trip context endpoints (docs/ui/API_MAP.md, S7): read, replace, parse free text.

Parsing is AI work, so it runs as a job (invariant 8); the job's result holds the proposed
structure, which the client shows for confirmation and then PUTs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.library.context import TripContext, load, revision, save

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
    body = {k: v for k, v in body.items() if k != "revision"}  # echoed back by GET
    try:
        ctx = TripContext.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        ) from None
    with _project(svc, me, pid) as project, project.write() as s:
        rev = save(s, ctx, "user")
    return {"revision": rev, **ctx.model_dump(mode="json")}


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
