"""Project settings (API_MAP ``/projects/{pid}/settings``; S8 Advanced, S21; ADR 0041).

A project overrides a few app settings and the analysis parameters of its mode. Values live
in the project DB (``project_meta`` row ``settings``, JSON), so they travel with the
project. Each effective value reports its source:

- ``project``: set for this project;
- ``user`` / ``default``: the app setting (S22);
- ``mode``: the analysis mode's own value (``value`` is null; the mode decides).
"""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any

from sqlalchemy.orm import Session

from mosaic.core.modes import PRESETS, ModeConfig, resolve
from mosaic.core.principal import Principal
from mosaic.storage.config import ConfigService
from mosaic.storage.models_project import ProjectMeta

META_KEY = "settings"

# Analysis parameters: project key → ModeConfig field.
ANALYSIS = {
    "analysis.sample_interval": "sample_interval",
    "analysis.tiles": "tiles",
    "analysis.forced_max_shot": "forced_max_shot",
    "analysis.proxy": "proxy",
    "analysis.stt_model": "stt_model",
}
# App settings a project may override: project key → app key.
FROM_APP = {
    "analysis.mode": "analysis.mode",
    "analysis.cost_limit_usd": "ai.budget.per_job_usd",
    "ai.send_gps": "ai.send_gps",
}
KEYS = (*FROM_APP, *ANALYSIS)


class ProjectSettingError(ValueError):
    pass


def _seconds(v: Any) -> str:
    try:
        f = Fraction(str(v))
    except (ValueError, ZeroDivisionError):
        raise ProjectSettingError(f"{v!r} is not a number of seconds") from None
    if not Fraction(1, 2) <= f <= 600:
        raise ProjectSettingError("seconds must be between 0.5 and 600")
    return str(f)


def coerce(key: str, value: Any) -> Any:
    """The stored form of ``value`` for ``key``; raises ``ProjectSettingError``."""
    if key == "analysis.mode":
        if value not in PRESETS:
            raise ProjectSettingError(f"mode must be one of {', '.join(PRESETS)}")
        return value
    if key == "analysis.cost_limit_usd":
        number = isinstance(value, int | float) and not isinstance(value, bool)
        if not number or not 0 <= value <= 10_000:
            raise ProjectSettingError("the cost limit is dollars between 0 and 10,000")
        return float(value)
    if key == "ai.send_gps":
        if not isinstance(value, bool):
            raise ProjectSettingError("ai.send_gps is true or false")
        return value
    if key in ("analysis.sample_interval", "analysis.forced_max_shot"):
        return _seconds(value)
    if key in ANALYSIS:
        # Validated as the mode parameter it overrides.
        try:
            ModeConfig.model_validate(
                PRESETS["balanced"].model_dump() | {ANALYSIS[key]: value, "name": "check"}
            )
        except ValueError as exc:
            raise ProjectSettingError(f"{key}: {exc}") from None
        return list(value) if key == "analysis.tiles" else value
    raise ProjectSettingError(f"unknown project setting {key!r}")


def stored(s: Session) -> dict[str, Any]:
    row = s.get(ProjectMeta, META_KEY)
    if row is None:
        return {}
    data = json.loads(row.value)
    return {k: v for k, v in data.items() if k in KEYS}


def patch(s: Session, values: dict[str, Any]) -> dict[str, Any]:
    """Sets the given keys (``None`` resets one to its app or mode value)."""
    current = stored(s)
    for key, value in values.items():
        if key not in KEYS:
            raise ProjectSettingError(f"unknown project setting {key!r}")
        if value is None:
            current.pop(key, None)
        else:
            current[key] = coerce(key, value)
    row = s.get(ProjectMeta, META_KEY)
    text = json.dumps(current, sort_keys=True)
    if row is None:
        s.add(ProjectMeta(key=META_KEY, value=text))
    else:
        row.value = text
    return current


def effective(
    s: Session, config: ConfigService, me: Principal, mode: str | None = None
) -> dict[str, dict[str, Any]]:
    """Every project setting with its source. Analysis parameters without an override
    report the value of ``mode`` (default: the project's mode) with source ``mode``."""
    mine = stored(s)
    app = config.settings(me)
    out: dict[str, dict[str, Any]] = {}
    for key, app_key in FROM_APP.items():
        if key in mine:
            out[key] = {"value": mine[key], "source": "project"}
        else:
            out[key] = {"value": app[app_key].value, "source": app[app_key].source}
    preset = PRESETS.get(mode or out["analysis.mode"]["value"], PRESETS["balanced"])
    base = preset.model_dump(mode="json")
    for key, field in ANALYSIS.items():
        if key in mine:
            out[key] = {"value": mine[key], "source": "project"}
        else:
            out[key] = {"value": base[field], "source": "mode"}
    return out


def mode_overrides(s: Session) -> dict[str, Any]:
    """The project's analysis overrides as ModeConfig fields (empty: the preset as is)."""
    mine = stored(s)
    return {field: mine[key] for key, field in ANALYSIS.items() if key in mine}


def run_config(mode: str, overrides: dict[str, Any]) -> ModeConfig:
    """``mode`` with the project's overrides: the preset itself when there are none, else
    a Custom run based on that preset (ADR 0041)."""
    if not overrides:
        return resolve(mode)
    return resolve("custom", {"base": mode, **overrides})
