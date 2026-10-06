"""Analysis endpoints (docs/ui/API_MAP.md "Analysis & jobs"; screens S8 and S25).

Without a scope, a run analyzes the whole project in a mode (Quick, Balanced, Thorough,
Custom). With a scope (the trip, some days, a selection), it deepens: it adds L2 where it
is missing and, for target Thorough, L3 on the candidates, reusing everything else
(ADR 0020). Both run as jobs (invariant 8).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.modes import MODES, ModeConfig, UnknownModeError, resolve
from mosaic.core.principal import Principal, check
from mosaic.library import estimate
from mosaic.library.review import TARGETS, DeepenScope, submit_deepen
from mosaic.media.pipeline import needs_benchmark, submit_analysis
from mosaic.storage.config import ConfigService

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["trip", "days", "selection"]
    days: list[int] = Field(default_factory=list, max_length=366)
    segment_ids: list[int] = Field(default_factory=list, max_length=100_000)

    @model_validator(mode="after")
    def _consistent(self) -> Scope:
        if self.kind == "days" and (not self.days or self.segment_ids):
            raise ValueError("scope days needs days (and no segment_ids)")
        if self.kind == "selection" and (not self.segment_ids or self.days):
            raise ValueError("scope selection needs segment_ids (and no days)")
        if self.kind == "trip" and (self.days or self.segment_ids):
            raise ValueError("scope trip takes no days or segment_ids")
        if any(d < 1 for d in self.days):
            raise ValueError("days are numbered from 1")
        return self

    def deepen(self) -> DeepenScope:
        return DeepenScope(tuple(sorted(set(self.days))), tuple(sorted(set(self.segment_ids))))


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    scope: Scope | None = None
    overrides: dict[str, Any] | None = None
    cost_limit: float | None = Field(default=None, ge=0)


def _mode(mode: str, overrides: dict[str, Any] | None, scope: Scope | None) -> ModeConfig:
    if scope is not None and mode not in TARGETS:
        raise HTTPException(422, f"deepening targets {' or '.join(TARGETS)}, not {mode!r}")
    if scope is not None and overrides:
        raise HTTPException(422, "overrides apply to a whole-project run, not to deepening")
    try:
        return resolve(mode, overrides)
    except UnknownModeError as exc:
        raise HTTPException(422, str(exc)) from None
    except ValidationError as exc:
        raise HTTPException(
            422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        ) from None


def _parse_scope(raw: str | None) -> Scope | None:
    """``trip`` | ``days:2,3`` | ``selection:101,102`` (query form of ``Scope``)."""
    if raw is None:
        return None
    kind, _, rest = raw.partition(":")
    try:
        ids = [int(x) for x in rest.split(",") if x.strip()]
        if kind == "days":
            return Scope(kind="days", days=ids)
        if kind == "selection":
            return Scope(kind="selection", segment_ids=ids)
        if kind == "trip" and not rest:
            return Scope(kind="trip")
    except (ValueError, ValidationError):
        pass
    raise HTTPException(422, "scope must be trip, days:N[,N…] or selection:ID[,ID…]")


@router.get("/projects/{pid}/analysis/estimate")
def get_estimate(
    pid: str,
    mode: str = Query(..., description=f"one of {', '.join(MODES)}"),
    scope: str | None = None,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    check(me, "analysis.read", pid)
    sc = _parse_scope(scope)
    config = _mode(mode, None, sc)
    cfg = ConfigService(svc.control)
    with _project(svc, me, pid) as project, project.db.session() as s:
        if sc is None:
            est = estimate.for_project(s, cfg, me, config)
        else:
            est = estimate.for_deepen(s, cfg, me, sc.deepen(), config)
    return est.as_json()


@router.post("/projects/{pid}/analysis-runs", status_code=202)
def post_run(pid: str, body: RunBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "analysis.run", pid)
    config = _mode(body.mode, body.overrides, body.scope)
    with _project(svc, me, pid, write=True) as project:
        if body.scope is None:
            job = submit_analysis(
                svc.executor,
                me,
                project,
                config,
                body.cost_limit,
                benchmark=needs_benchmark(svc.control),
            )
            return {"job_id": job, "mode": config.model_dump(mode="json")}
        run = submit_deepen(
            svc.executor,
            me,
            project,
            body.scope.deepen(),
            target=config.name,
            cost_limit_usd=body.cost_limit,
        )
    return {
        "job_id": run.job,  # null: nothing to add in this scope
        "candidates": run.candidates,
        "l2_assets": run.l2_assets,
        "dropped": run.dropped,
    }
