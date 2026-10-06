"""``/api/jobs`` and ``/api/events`` (SSE), per docs/ui/API_MAP.md."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.core.time import format_display
from mosaic.jobs.model import JOB_TERMINAL, JobProgress
from mosaic.storage.models_control import Job

router = APIRouter(prefix="/api")
TERMINAL_STATES = frozenset(s.value for s in JOB_TERMINAL)

Svc = Depends(services)
Me = Depends(principal)


def ui_state(status: str) -> str:
    """API_MAP job states; a not-yet-started job is reported as running."""
    return "running" if status == "pending" else status


def _progress_json(p: JobProgress) -> dict[str, Any]:
    from fractions import Fraction

    eta = (
        None
        if p.eta_ms is None
        else {"ms": p.eta_ms, "display": format_display(Fraction(p.eta_ms, 1000))}
    )
    return {
        "job_id": p.job_id,
        "project_id": p.project_id,
        "kind": p.kind,
        "state": ui_state(p.status),
        "stage": p.stage,
        "pct": p.pct,
        "done": p.done,
        "total": p.total,
        "failed": p.failed,
        "item": p.current_item,
        "cost": {"usd": p.cost_usd},
        "eta": eta,
    }


def _job_json(svc: Services, job: Job) -> dict[str, Any]:
    prog = svc.store.progress(job.id)
    return {
        "job_id": job.id,
        "project_id": job.project_id,
        "kind": job.kind,
        "state": ui_state(job.status),
        "stage": job.stage,
        "created_at": job.created_at,
        "error": job.error,
        "result": job.result,
        "cost_usd": job.cost_usd,
        "cost_limit_usd": job.cost_limit_usd,
        "progress": _progress_json(prog) if prog else None,
    }


@router.get("/jobs")
def list_jobs(
    project: str | None = None,
    active: bool | None = None,
    cursor: int | None = None,
    limit: int = 50,
    svc: Services = Svc,
    _me: Principal = Me,
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    jobs = svc.store.jobs(project, active, cursor=cursor, limit=limit + 1)
    page = jobs[:limit]
    next_cursor = page[-1].id if len(jobs) > limit else None
    return {"items": [_job_json(svc, j) for j in page], "next_cursor": next_cursor}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, svc: Services = Svc, _me: Principal = Me) -> dict[str, Any]:
    job = svc.store.job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    out = _job_json(svc, job)
    out["stages"] = svc.store.stage_counts(job_id)
    return out


class ResumeBody(BaseModel):
    """Optional on resume: a higher AI cost limit (a cost-limit pause needs one)."""

    model_config = ConfigDict(extra="forbid")

    cost_limit_usd: float | None = Field(default=None, ge=0)


@router.post("/jobs/{job_id}/{action}")
def control_job(
    job_id: int,
    action: str,
    body: ResumeBody | None = None,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    current = svc.store.job(job_id)
    if current is None:
        raise HTTPException(404, "job not found")
    ex = svc.executor
    if body is not None and action != "resume":
        raise HTTPException(422, f"{action} takes no body")
    if action == "cancel":
        ex.cancel(me, job_id)
    elif action == "pause":
        ex.pause(me, job_id)
    elif action == "resume":
        check(me, "job.resume", str(job_id))  # before touching the limit
        if body is not None and body.cost_limit_usd is not None:
            # Equal to the spend would pause again at the next reservation.
            if body.cost_limit_usd <= (current.cost_usd or 0):
                raise HTTPException(422, "the cost limit must be above what the job has spent")
            svc.store.set_cost_limit(job_id, body.cost_limit_usd)
        ex.resume(me, job_id)
    elif action == "retry-failed":
        ex.retry_failed(me, job_id)
    else:
        raise HTTPException(404, "unknown action")
    job = svc.store.job(job_id)
    assert job is not None
    return _job_json(svc, job)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/events")
async def events(
    request: Request,
    project: str | None = None,
    until_idle: bool = False,
    svc: Services = Svc,
    _me: Principal = Me,
) -> StreamingResponse:
    """Server-sent events: ``job.progress``, ``job.stage``, ``job.state``,
    ``analysis.ready_to_browse`` (once per analysis job, when L0 and L1 are done),
    ``clip.updated`` (a library decision changed) and ``lock.lost``. Without ``project``:
    every project's jobs (the rail's activity ring, S0), and ``lock.lost`` for any project
    this server lost."""

    async def stream() -> AsyncIterator[str]:
        hub = svc.events.subscribe()
        try:
            async for chunk in _stream(hub):
                yield chunk
        finally:  # the client went away, or the stream ended
            svc.events.unsubscribe(hub)

    async def _stream(hub: Any) -> AsyncIterator[str]:
        from mosaic.library.progress_view import (
            ready_to_browse,
            stage_levels,
            stage_status_counts,
        )

        seen: dict[int, dict[str, Any]] = {}
        lost_sent: set[str] = set()
        ready_sent: set[int] = set()
        levels = stage_levels()
        yield ": connected\n\n"
        first = True
        while not await request.is_disconnected():
            active = 0
            # First pass: all of the project's recent jobs; then only active ones plus jobs
            # we are already following (so their final state is delivered).
            candidates = svc.store.jobs(project, None if first else True, limit=200)
            tracked = {j.id for j in candidates}
            for jid, followed in seen.items():
                if jid not in tracked and followed["state"] not in TERMINAL_STATES:
                    job_row = svc.store.job(jid)
                    if job_row is not None:
                        candidates.append(job_row)
            first = False
            for job in candidates:
                prog = svc.store.progress(job.id)
                if prog is None:
                    continue
                cur = _progress_json(prog)
                prev = seen.get(job.id)
                if prev is None and job.status in {s.value for s in JOB_TERMINAL}:
                    seen[job.id] = cur
                    continue
                if prev is None or prev["state"] != cur["state"]:
                    yield _sse("job.state", {"job_id": job.id, "state": cur["state"]})
                if prev is None or prev["stage"] != cur["stage"]:
                    yield _sse("job.stage", {"job_id": job.id, "stage": cur["stage"]})
                if prev != cur:
                    yield _sse(
                        "job.progress",
                        {
                            **{k: cur[k] for k in ("job_id", "pct", "stage", "item", "cost")},
                            "project_id": job.project_id,
                            "kind": job.kind,
                            "state": cur["state"],
                        },
                    )
                if job.kind == "analysis" and job.id not in ready_sent:
                    with svc.control.db.session() as cs:
                        ready = ready_to_browse(stage_status_counts(cs, job.id), levels)
                    if ready:
                        ready_sent.add(job.id)
                        yield _sse(
                            "analysis.ready_to_browse",
                            {"job_id": job.id, "project_id": job.project_id},
                        )
                seen[job.id] = cur
                active += job.status not in {s.value for s in JOB_TERMINAL}
            for pid in sorted(svc.leases.lost):
                if (project is None or pid == project) and pid not in lost_sent:
                    lost_sent.add(pid)  # another computer took it over (ADR 0023)
                    yield _sse("lock.lost", {"project_id": pid})
            while True:  # clip.updated and other non-job events
                try:
                    event, data = hub.popleft()
                except IndexError:  # empty, or emptied by an overflow just now
                    break
                if project is None or data.get("project_id") == project:
                    yield _sse(event, data)
            if until_idle and not active:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
