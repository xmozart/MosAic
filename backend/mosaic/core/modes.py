"""Analysis modes (ANALYSIS_MODES.md §2): Quick, Balanced, Thorough and Custom.

A mode is a set of parameters each stage reads from its job; every parameter that changes
a stage's output is part of that stage's artifact key, so running another mode reuses
whatever matches and recomputes only what differs. Deepening a scope (a day, a selection)
only *adds* levels (L2 if missing, L3) on top of the existing L0/L1 — it never recomputes
them (M1 acceptance 5, ADR 0020).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator

Detector = Literal["threshold", "adaptive"]
Proxy = Literal["lrf_or_540", "720"]
# faster-whisper models with pinned revisions (ai/adapters/faster_whisper/transcriber.py).
SttModel = Literal["small", "medium", "large-v3"]


class ModeConfig(BaseModel):
    """Every per-mode analysis parameter. Seconds are exact fractions (as strings in JSON)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    proxy: Proxy = "720"
    sample_interval: Fraction = Fraction(3)
    detector: Detector = "adaptive"
    forced_max_shot: Fraction = Fraction(60)
    tiles: tuple[int, int] = (4, 4)  # cols × rows per contact sheet
    stt_model: SttModel | None = None  # None: the transcriber's provider profile
    l2: bool = True
    l3: bool = False
    # The preset a Custom run starts from (ADR 0041): its speed factor and the name the
    # owner chose. Not a stage parameter, so no artifact key reads it.
    base: Literal["quick", "balanced", "thorough"] | None = None

    @property
    def preset(self) -> str:
        """The preset this run is, or is based on."""
        return self.base or self.name

    @field_validator("sample_interval", "forced_max_shot", mode="before")
    @classmethod
    def _frac(cls, v: Any) -> Fraction:
        f = Fraction(str(v)) if not isinstance(v, Fraction) else v
        if f <= 0:
            raise ValueError("must be positive")
        return f

    @field_validator("tiles")
    @classmethod
    def _tiles(cls, v: tuple[int, int]) -> tuple[int, int]:
        cols, rows = v
        if not (2 <= cols <= 8 and 2 <= rows <= 8):
            raise ValueError("tiles must be between 2×2 and 8×8")
        return v

    @model_validator(mode="after")
    def _levels(self) -> ModeConfig:
        if self.l3 and not self.l2:
            raise ValueError("L3 reviews L2 candidates: l3 needs l2")
        return self

    @field_serializer("sample_interval", "forced_max_shot")
    def _ser(self, v: Fraction) -> str:
        return str(v)


PRESETS: dict[str, ModeConfig] = {
    "quick": ModeConfig(
        name="quick",
        proxy="lrf_or_540",
        sample_interval=Fraction(6),
        detector="threshold",
        forced_max_shot=Fraction(60),
        tiles=(6, 4),  # 24 small tiles
        stt_model="small",
    ),
    "balanced": ModeConfig(name="balanced"),
    "thorough": ModeConfig(
        name="thorough",
        sample_interval=Fraction(3, 2),
        forced_max_shot=Fraction(30),  # adaptive + forced subdivision of long shots
        tiles=(4, 3),  # 12 tiles, plus L3 single frames
        stt_model="large-v3",
        l3=True,
    ),
}
MODES = (*PRESETS, "custom")


class UnknownModeError(ValueError):
    pass


def resolve(mode: str, overrides: dict[str, Any] | None = None) -> ModeConfig:
    """A preset, or ``custom``: a preset (``base``, default Balanced) with explicit
    overrides (S8 Advanced; ADR 0041)."""
    if mode == "custom":
        rest = dict(overrides or {})
        base_name = rest.pop("base", "balanced")
        if base_name not in PRESETS:
            raise UnknownModeError(f"custom is based on one of {', '.join(PRESETS)}")
        base = PRESETS[base_name].model_dump()
        return ModeConfig.model_validate(base | rest | {"name": "custom", "base": base_name})
    if mode not in PRESETS:
        raise UnknownModeError(f"unknown analysis mode {mode!r}; choose one of {', '.join(MODES)}")
    if overrides:
        raise UnknownModeError("overrides are only accepted with mode custom")
    return PRESETS[mode]


def from_params(params: dict[str, Any] | None) -> ModeConfig:
    """The mode a job was submitted with (Balanced for jobs from before modes)."""
    data = (params or {}).get("mode_config")
    if data:
        return ModeConfig.model_validate(data)
    return resolve(str((params or {}).get("mode", "balanced")))


def task_mode(ctx: Any) -> ModeConfig:
    job = ctx.store.job(ctx.task.job_id)
    return from_params(job.params if job else None)
