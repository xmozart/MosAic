"""Output schema for review v1 (L3): one observation of one segment from full-resolution
frames, in the same vocabulary as vision v1 so dispositions and retrieval read either."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mosaic.ai.prompts.vision.schema_v1 import (
    CameraMotion,
    Composition,
    Interest,
    Issue,
    People,
    ShotType,
)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=3, max_length=300)
    subjects: list[str] = Field(max_length=8)
    shot_type: ShotType
    camera_motion: CameraMotion
    people: People
    interest: Interest
    composition: Composition
    issues: list[Issue]
    usable: bool
    best_frame: str = Field(pattern=r"^F[1-9]$")
    main_subject_visible: bool
