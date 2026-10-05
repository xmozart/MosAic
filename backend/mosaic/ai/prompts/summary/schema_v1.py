"""Output schema for summary v1: one day's or the whole trip's summary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=3, max_length=1200)
    themes: list[str] = Field(max_length=6)
    highlights: list[str] = Field(max_length=8)
