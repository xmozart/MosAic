"""``context.parse``: free text → a proposed TripContext for the owner to confirm.

The proposal is the task's result; nothing is stored until the owner confirms it
(`mosaic context parse … --yes` or the confirmation prompt), PRODUCT.md §3.
"""

from __future__ import annotations

from typing import Any

from mosaic.ai.client import AIClient
from mosaic.core.clock import now_iso
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import task
from mosaic.library.context import TripContext

PROMPT = ("context_parse", 1)


@task("context.parse")
def parse_task(ctx: TaskContext) -> dict[str, Any]:
    text = str(ctx.params["text"])
    result = AIClient(ctx).structured(
        "planner",
        *PROMPT,
        {"text": text, "today": now_iso()[:10]},
        max_tokens=4000,
    )
    proposal = result.data
    assert isinstance(proposal, TripContext)
    out = {"proposal": proposal.model_dump(mode="json"), "cached": result.cached}
    # S7 reads the proposal from ``GET /jobs/{id}`` to show it for confirmation.
    ctx.store.set_job_result(ctx.task.job_id, {"proposal": out["proposal"]})
    return out
