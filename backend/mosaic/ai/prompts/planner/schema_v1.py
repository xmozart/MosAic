"""Output schema for planner v1: the story as ordered beats with candidate pools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Beat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(pattern=r"^b[0-9]{1,2}$")
    title: str = Field(min_length=2, max_length=60)
    intent: str = Field(min_length=3, max_length=300)
    share_percent: int = Field(ge=3, le=80)
    candidates: list[str] = Field(min_length=1, max_length=60)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=80)
    beats: list[Beat] = Field(min_length=1, max_length=12)
