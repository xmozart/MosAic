"""Identifiers: ULIDs for projects and edits; prefixed display ids for rows."""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(timestamp_ms: int | None = None) -> str:
    """26-character Crockford base32 ULID (48-bit ms timestamp + 80 random bits)."""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


PREFIX_WIDTH = {
    "ast": 4,
    "mf": 5,
    "shot": 5,
    "seg": 6,
    "prov": 5,
    "smp": 6,
    "mos": 5,
    "evt": 4,
    "beat": 2,
    "grp": 4,
    "task": 6,
    "job": 5,
    "render": 4,
}


def fmt_id(prefix: str, n: int) -> str:
    """``fmt_id("seg", 451)`` → ``"seg_000451"`` (ARCHITECTURE.md §5.3 examples)."""
    return f"{prefix}_{n:0{PREFIX_WIDTH.get(prefix, 4)}d}"


def parse_id(prefix: str, value: str) -> int:
    head, _, num = value.partition("_")
    if head != prefix or not num.isdigit():
        raise ValueError(f"not a {prefix} id: {value!r}")
    return int(num)
