"""Typed app settings and provider profiles: shipped defaults (``core/defaults.toml``)
overridden by the owner's choices in the control DB (ADR 0003)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULTS_FILE = Path(__file__).with_name("defaults.toml")

CAPABILITIES = ("vision", "planner", "selector", "critic", "transcriber", "embedder")
CLOUD_CAPABILITIES = ("vision", "planner", "selector", "critic")


@dataclass(frozen=True)
class ProviderChoice:
    capability: str
    provider: str
    model: str
    mode: str  # cloud|local


@lru_cache(maxsize=1)
def defaults() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads(DEFAULTS_FILE.read_text())
    return data


def default_settings() -> dict[str, Any]:
    out: dict[str, Any] = dict(defaults()["settings"])
    return out


def default_provider(capability: str) -> ProviderChoice:
    entry = defaults()["providers"][capability]
    return ProviderChoice(capability, entry["provider"], entry["model"], entry["mode"])


class SettingError(ValueError):
    pass


def coerce(key: str, value: Any) -> Any:
    """Validate ``value`` for a known setting, converting CLI strings to the default's type."""
    known = default_settings()
    if key not in known:
        raise SettingError(f"unknown setting {key!r}; known: {', '.join(sorted(known))}")
    default = known[key]
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        raise SettingError(f"{key} expects true or false")
    if isinstance(default, float):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise SettingError(f"{key} expects a number") from exc
        if number < 0:
            raise SettingError(f"{key} must not be negative")
        return number
    if key.endswith("_dir") and value:
        path = Path(str(value)).expanduser()
        if not path.is_dir():
            raise SettingError(f"{key}: folder not found: {path}")
        return str(path.resolve())
    return str(value)
