"""Output schema for selector v2: ordered selections per beat (ARCHITECTURE.md §9).

Decisions only: which clip, role, priority, a length class and audio intent. The solver
computes every duration and position (invariant 5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal[
    "opener",
    "establishing",
    "hero",
    "detail",
    "action",
    "people",
    "reaction",
    "dialogue",
    "transition",
    "b_roll",
    "closer",
]
Length = Literal["short", "medium", "long", "hold"]
AudioIntent = Literal["dialogue", "natural_sound", "natural_sound_low", "mute"]


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(pattern=r"^seg_[0-9]{6}$")
    why_not: str = Field(min_length=2, max_length=160)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(pattern=r"^seg_[0-9]{6}$")
    role: Role
    priority: int = Field(ge=1, le=5)
    length: Length
    audio_intent: AudioIntent
    reason: str = Field(min_length=3, max_length=240)
    alternatives: list[Alternative] = Field(max_length=3)


class BeatSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(pattern=r"^b[0-9]{1,2}$")
    selections: list[Selection] = Field(min_length=1, max_length=40)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beats: list[BeatSelection]
