"""Output schema for critic v1 (M4: "the AI critic takes the EDL plus summaries and
returns structured suggestions"; ADR 0082). Notes about the cut, each about one event by
its id or about the whole edit; decisions only, never timings or media operations
(invariant 5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str | None = Field(default=None, pattern=r"^evt_[0-9]{4,}$")
    action: Literal["remove", "replace", "note"]
    severity: Literal["warning", "info"]
    text: str = Field(min_length=10, max_length=240)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: list[Note] = Field(default_factory=list, max_length=8)
