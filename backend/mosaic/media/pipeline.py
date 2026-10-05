"""Analysis runs: the job that drives L0/L1/L2 for a project (ARCHITECTURE.md §8)."""

from __future__ import annotations

from mosaic.core.principal import Principal
from mosaic.jobs.executor import Executor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.storage.projects import Project

SUPPORTED_MODES = ("balanced",)


class UnsupportedModeError(ValueError):
    pass


def job_cost_limit(principal: Principal) -> float:
    """Per-job AI budget from the ``ai.budget.per_job_usd`` setting (ANALYSIS_MODES §4)."""
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    try:
        return float(ConfigService(control).get(principal, "ai.budget.per_job_usd"))
    finally:
        control.db.dispose()


def submit_analysis(
    executor: Executor,
    principal: Principal,
    project: Project,
    mode: str = "balanced",
    cost_limit_usd: float | None = None,
) -> int:
    """Start an analysis run. M0 accepts only ``balanced`` (ADR 0002 M)."""
    if mode not in SUPPORTED_MODES:
        raise UnsupportedModeError(
            f"analysis mode {mode!r} is not available yet; M0 supports: balanced"
        )
    return executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="analysis",
            params={"mode": mode},
            cost_limit_usd=(
                job_cost_limit(principal) if cost_limit_usd is None else cost_limit_usd
            ),
            tasks=[
                TaskSpec(
                    kind="analysis.scan",
                    stage="scan",
                    resource_class=ResourceClass.IO,
                    label="scanning folder",
                )
            ],
        ),
    )
