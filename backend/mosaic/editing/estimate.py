"""Edit estimates (S14's summary panel; ADR 0047).

Retrieval runs as it would for the edit (no AI call), so the estimate knows the real
candidate pool: its size sets the planner's and selector's input tokens, its usable
length says whether the footage can fill the requested duration, and the edit's key says
whether an identical plan already exists (then the AI cache answers: no cost, seconds).

Every value is for display: seconds and dollars are rounded, nothing is stored or used as
an authoritative time (invariant 3); the target itself is returned in frames.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.ai.adapters.base import estimate_text_tokens
from mosaic.ai.registry import price_for
from mosaic.core.principal import Principal
from mosaic.editing.generate import (
    CAPABILITIES,
    PLANNER_MAX_TOKENS,
    SELECTOR_MAX_TOKENS,
    edit_inputs,
    edit_key,
)
from mosaic.editing.request import EditRequest, target_frames
from mosaic.library.estimate import OUTPUT_SHARE, TEXT_TOKENS
from mosaic.storage.config import ConfigService
from mosaic.storage.models_project import EditVersion

# Wall time of one planner or selector call (display only; M0 runs took tens of seconds
# to about two minutes per call on long candidate lists).
CALL_SECONDS = (20, 120)
REUSE_SECONDS = (2, 10)  # an identical plan: retrieval, the solver and a render-free commit


def for_request(
    s: Session,
    config: ConfigService,
    me: Principal,
    project_id: str,
    req: EditRequest,
    analysis_pct: int | None = None,
) -> dict[str, Any]:
    """``analysis_pct``: how far a running analysis is (None: none is running)."""
    inp = edit_inputs(s, req)
    choices = {cap: config.provider(me, cap) for cap in CAPABILITIES}
    reuses = (
        s.scalar(
            select(EditVersion.id)
            .where(EditVersion.key == edit_key(project_id, req, inp, choices))
            .limit(1)
        )
        is not None
    )
    pool = estimate_text_tokens("\n".join(c.line() for c in inp.cands))
    plan_out = (
        math.floor(PLANNER_MAX_TOKENS * OUTPUT_SHARE[0]),
        math.floor(PLANNER_MAX_TOKENS * OUTPUT_SHARE[1]),
    )
    sel_out = (
        math.floor(SELECTOR_MAX_TOKENS * OUTPUT_SHARE[0]),
        math.floor(SELECTOR_MAX_TOKENS * OUTPUT_SHARE[1]),
    )
    cost: list[float] | None = [0.0, 0.0]
    if not reuses and inp.cands:
        p_plan, p_sel = price_for(choices["planner"]), price_for(choices["selector"])
        if p_plan is None or p_sel is None:
            cost = None
        else:
            cost = [
                round(
                    (
                        (TEXT_TOKENS + pool) * p_plan[0]
                        + plan_out[i] * p_plan[1]
                        + (TEXT_TOKENS + pool + plan_out[i]) * p_sel[0]
                        + sel_out[i] * p_sel[1]
                    )
                    / 1_000_000,
                    2,
                )
                for i in (0, 1)
            ]
    usable = sum((c.usable_seconds for c in inp.cands), Fraction(0))
    wall = REUSE_SECONDS if reuses else (2 * CALL_SECONDS[0], 2 * CALL_SECONDS[1])
    return {
        "candidates": len(inp.cands),
        "target": {"frames": target_frames(req.duration_s, inp.rate), "rate": inp.rate},
        "usable_seconds": math.floor(usable),  # display
        "enough_footage": usable >= req.duration_s,
        "reuses_plan": reuses,
        "cost_usd": cost,
        "wall_seconds": list(wall) if inp.cands else [0, 0],
        "preliminary": analysis_pct is not None,
        "analysis_pct": analysis_pct,
    }
