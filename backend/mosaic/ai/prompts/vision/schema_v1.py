"""Output schema for vision v1: one observation per segment of a contact sheet.

Scores are ordinal (ARCHITECTURE.md §5.3). The model cites segments as ``S1``… and tiles as
``T01``…; code resolves both to rows and source ticks (§8 stage 10).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShotType = Literal[
    "establishing_wide",
    "wide",
    "medium",
    "close_up",
    "detail",
    "aerial",
    "pov",
    "selfie",
    "other",
]
CameraMotion = Literal[
    "static",
    "pan",
    "tilt",
    "push_in",
    "pull_out",
    "tracking",
    "handheld_walk",
    "vehicle",
    "erratic",
]
People = Literal["none", "one", "few", "group", "crowd"]
Interest = Literal["low", "medium", "high"]
Composition = Literal["poor", "fair", "good", "excellent"]
Issue = Literal[
    "accidental",
    "pocket_or_covered",
    "obstructed",
    "lens_dirty",
    "out_of_focus",
    "motion_blur",
    "shaky",
    "too_dark",
    "overexposed",
    "tilted",
    "nothing_happens",
]


class SegmentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment: str = Field(pattern=r"^S[1-9][0-9]?$")
    description: str = Field(min_length=3, max_length=240)
    subjects: list[str] = Field(max_length=6)
    shot_type: ShotType
    camera_motion: CameraMotion
    people: People
    interest: Interest
    composition: Composition
    issues: list[Issue]
    usable: bool
    best_tile: str = Field(pattern=r"^T[0-9]{2}$")


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[SegmentObservation]
