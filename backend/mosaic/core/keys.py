"""Canonical hashing for artifact keys and config hashes (CLAUDE.md invariant 9).

A key is a hash of the inputs, the config and the algorithm or prompt version. Keys always
include the project id (FUTURE_APPENDIX §2 guard).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import Enum
from fractions import Fraction
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel

KEY_LENGTH = 40


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_normalize(v) for v in value)
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, float):
        # Floats may appear in config (thresholds); repr is exact and stable.
        return {"__float__": repr(value)}
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(value: Any, length: int = KEY_LENGTH) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()[:length]


def artifact_key(
    kind: str,
    *,
    project_id: str,
    inputs: Any,
    config: Any = None,
    version: str,
) -> str:
    """Deterministic key for an artifact; identical keys mean no recompute."""
    body = {
        "kind": kind,
        "project": project_id,
        "inputs": inputs,
        "config": config,
        "version": version,
    }
    return f"{kind}-{digest(body)}"


def config_hash(config: Any) -> str:
    return digest(config, 16)
