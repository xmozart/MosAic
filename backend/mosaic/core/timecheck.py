"""Detect float-second time values (CLAUDE.md invariant 3, M0 acceptance 4).

Non-time floats (LUFS, sharpness, cost) are allowed; a float, or a decimal string, under a
time-like key is not.
"""

from __future__ import annotations

import re
from typing import Any

TIME_LIKE = re.compile(
    r"(^|_)(time|times|start|end|duration|dur|pts|dts|offset|in|out|seconds|secs|sec|ts|"
    r"timestamp|position|pos|at|tc|trim|head|tail)($|_)",
    re.I,
)
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def is_time_like(name: str) -> bool:
    return bool(TIME_LIKE.search(name))


def find_float_times(value: Any, path: str = "$") -> list[str]:
    """Paths of float (or decimal-string) values stored under time-like keys."""
    found: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}"
            if is_time_like(str(k)) and (
                isinstance(v, float) or (isinstance(v, str) and _DECIMAL.match(v))
            ):
                found.append(p)
            found += find_float_times(v, p)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += find_float_times(v, f"{path}[{i}]")
    return found
