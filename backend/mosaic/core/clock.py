"""Wall-clock timestamps for audit fields (ISO-8601 strings with offset, never floats)."""

from __future__ import annotations

from datetime import datetime


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
