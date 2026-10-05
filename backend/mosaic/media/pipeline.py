"""Analysis runs: the job that drives L0/L1/L2 for a project (ARCHITECTURE.md §8)."""

from __future__ import annotations

from typing import Any

from mosaic.core.modes import ModeConfig, resolve
from mosaic.core.principal import Principal
from mosaic.jobs.executor import Executor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.storage.projects import Project


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
    mode: str | ModeConfig = "balanced",
    cost_limit_usd: float | None = None,
    overrides: dict[str, Any] | None = None,
) -> int:
    """Start an analysis run of the whole project in ``mode`` (ANALYSIS_MODES §2). Each
    stage reads the mode from the job; whatever already matches its key is reused.
    Raises ``modes.UnknownModeError`` or a validation error for a bad mode."""
    config = mode if isinstance(mode, ModeConfig) else resolve(mode, overrides)
    return executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="analysis",
            params={"mode": config.name, "mode_config": config.model_dump(mode="json")},
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
