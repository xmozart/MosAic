"""Analysis endpoints (docs/ui/API_MAP.md "Analysis & jobs"; screens S8 and S25).

Without a scope, a run analyzes the whole project in a mode (Quick, Balanced, Thorough,
Custom). With a scope (the trip, some days, a selection), it deepens: it adds L2 where it
is missing and, for target Thorough, L3 on the candidates, reusing everything else
(ADR 0020). Both run as jobs (invariant 8).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.modes import MODES, PRESETS, ModeConfig, UnknownModeError, resolve
from mosaic.core.principal import Principal, check
from mosaic.library import estimate
from mosaic.library.review import TARGETS, DeepenScope, submit_deepen
from mosaic.media.pipeline import needs_benchmark, submit_analysis
from mosaic.storage import project_settings
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


def _project_mode(s: Any, mode: str, overrides: dict[str, Any] | None) -> ModeConfig:
    """A whole-project run in a preset: the preset with the project's Advanced overrides
    (or, for an estimate of unsaved S8 edits, ``overrides`` given here; ADR 0041)."""
    if mode == "custom":
        return _mode(mode, overrides, None)
    if mode not in PRESETS:
        return _mode(mode, None, None)  # 422 with the list of modes
    stored = project_settings.mode_overrides(s) if overrides is None else overrides
    try:
        return project_settings.run_config(mode, stored)
    except (UnknownModeError, ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


def _overrides_query(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(422, "overrides must be a JSON object") from None
    if not isinstance(data, dict):
        raise HTTPException(422, "overrides must be a JSON object")
    fields = dict(project_settings.ANALYSIS)
    unknown = [k for k in data if k not in fields]
    if unknown:
        raise HTTPException(422, f"unknown analysis setting {unknown[0]!r}")
    try:  # the same checks as PATCH /settings
        return {fields[k]: project_settings.coerce(k, v) for k, v in data.items() if v is not None}
    except project_settings.ProjectSettingError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/projects/{pid}/analysis/estimate")
def get_estimate(
    pid: str,
    mode: str = Query(..., description=f"one of {', '.join(MODES)}"),
    scope: str | None = None,
    overrides: str | None = Query(
        None, description="JSON of project analysis keys: estimate unsaved S8 edits"
    ),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    check(me, "analysis.read", pid)
    sc = _parse_scope(scope)
    if sc is not None and overrides is not None:
        raise HTTPException(422, "overrides apply to a whole-project run, not to deepening")
    edits = _overrides_query(overrides)
    cfg = ConfigService(svc.control)
    with _project(svc, me, pid) as project, project.db.session() as s:
        if sc is None:
            config = _project_mode(s, mode, edits)
            est = estimate.for_project(s, cfg, me, config)
        else:
            est = estimate.for_deepen(s, cfg, me, sc.deepen(), _mode(mode, None, sc))
    return est.as_json()


@router.post("/projects/{pid}/analysis-runs", status_code=202)
def post_run(pid: str, body: RunBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "analysis.run", pid)
    config = _mode(body.mode, body.overrides, body.scope)
    with _project(svc, me, pid, write=True) as project:
        cost_limit = body.cost_limit
        with project.db.session() as s:
            if cost_limit is None:  # the project's limit, else the app's (ADR 0041)
                cost_limit = project_settings.stored(s).get("analysis.cost_limit_usd")
            if body.scope is None and body.mode in PRESETS:
                # A preset carries the project's Advanced overrides.
                config = _project_mode(s, body.mode, None)
        if body.scope is None:
            job = submit_analysis(
                svc.executor,
                me,
                project,
                config,
                cost_limit,
                benchmark=needs_benchmark(svc.control),
            )
            return {"job_id": job, "mode": config.model_dump(mode="json")}
        run = submit_deepen(
            svc.executor,
            me,
            project,
            body.scope.deepen(),
            target=config.name,
            cost_limit_usd=cost_limit,
        )
    return {
        "job_id": run.job,  # null: nothing to add in this scope
        "candidates": run.candidates,
        "l2_assets": run.l2_assets,
        "dropped": run.dropped,
    }


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(max_length=32)


@router.get("/projects/{pid}/settings")
def get_project_settings(
    pid: str, mode: str | None = None, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """Effective project settings with their source (project, user, default or mode).
    ``mode`` shows the analysis parameters of that preset where the project sets none."""
    check(me, "settings.read", pid)
    if mode is not None and mode not in PRESETS:
        raise HTTPException(422, f"mode must be one of {', '.join(PRESETS)}")
    with _project(svc, me, pid) as project, project.db.session() as s:
        return {"settings": project_settings.effective(s, ConfigService(svc.control), me, mode)}


@router.patch("/projects/{pid}/settings")
def patch_project_settings(
    pid: str, body: SettingsPatch, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """Sets project settings; a null value resets one to its app or mode value."""
    check(me, "settings.write", pid)
    with _project(svc, me, pid, write=True) as project:
        try:
            with project.write() as s:
                project_settings.patch(s, body.values)
        except project_settings.ProjectSettingError as exc:
            raise HTTPException(422, str(exc)) from None
        with project.db.session() as s:
            return {"settings": project_settings.effective(s, ConfigService(svc.control), me)}


@router.get("/projects/{pid}/analysis/progress")
def get_progress(
    pid: str, job: int | None = None, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """S9: the analysis (or deepening) job's steps in plain words, the live contact sheet,
    failed clips and whether the library can be browsed (ADR 0041). Without ``job``: the
    project's latest analysis or deepening job; 404 when it has none."""
    from mosaic.library.progress_view import analysis_progress

    check(me, "analysis.read", pid)
    if job is None:
        latest = [
            j
            for kind in ("analysis", "deepen")
            for j in svc.store.jobs(pid, None, kind=kind, limit=1)
        ]
        row = max(latest, key=lambda j: j.id, default=None)
    else:
        row = svc.store.job(job)
    if row is None or row.project_id != pid or row.kind not in ("analysis", "deepen"):
        raise HTTPException(404, "no analysis job")
    with (
        _project(svc, me, pid) as project,
        project.db.session() as s,
        svc.control.db.session() as control,
    ):
        return analysis_progress(control, s, row)
