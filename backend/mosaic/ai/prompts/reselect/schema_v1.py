"""Output schema for reselect v1: new selections for one beat's free slots, in order
(ADR 0069). Decisions only; the solver computes every duration and position (invariant 5)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mosaic.ai.prompts.selector.schema_v2 import Selection


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(pattern=r"^b[0-9]{1,2}$")
    selections: list[Selection] = Field(min_length=1, max_length=40)
