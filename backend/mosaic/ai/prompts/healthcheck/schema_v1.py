"""Output schema for healthcheck v1."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
