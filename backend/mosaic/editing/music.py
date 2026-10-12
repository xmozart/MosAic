"""The music bed (M4: "a basic music bed (user track, fades, static level, simple ducking
under detected speech)"; ADR 0080).

One track the owner chose lies under the whole edit: looped when it is shorter, at a
static level, faded in and out, and ducked by a fixed amount wherever the edit plays
dialogue. The track is read, never changed (invariant 1); beat-synced cutting is M6.
"""

from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path
from typing import Any

DUCK_DB = -12  # under speech, relative to the track's level
DUCK_RAMP = Fraction(1, 4)  # seconds into and out of each duck


class MusicPathError(ValueError):
    """The music track cannot be used; the message is for the owner."""


def check_path(path: str) -> Path:
    """The track at ``path``: an absolute path to a readable file."""
    if "\x00" in path:
        raise MusicPathError("Invalid path.")
    p = Path(path)
    if not p.is_absolute():
        raise MusicPathError("Use the music track's full path.")
    if not p.is_file():
        raise MusicPathError(f"{p.name}: no such file.")
    if not os.access(p, os.R_OK):
        raise MusicPathError(f"{p.name}: the file can't be read.")
    return p


def speech_windows(timeline: dict[str, Any], merge_frames: int) -> list[tuple[int, int]]:
    """Where the edit plays dialogue, in timeline frames: each dialogue event's heard
    window (its own audio window after a J- or L-cut, ADR 0077), with windows closer
    than ``merge_frames`` joined so the music does not bob between sentences."""
    spans = []
    for e in timeline["tracks"][0]["events"]:
        a = e.get("audio") or {}
        if a.get("intent") != "dialogue" or not a.get("source_enabled"):
            continue
        w = a if "timeline_in" in a else e
        spans.append((int(w["timeline_in"]["frames"]), int(w["timeline_out"]["frames"])))
    out: list[tuple[int, int]] = []
    for s, t in sorted(spans):
        if out and s - out[-1][1] <= merge_frames:
            out[-1] = (out[-1][0], max(out[-1][1], t))
        else:
            out.append((s, t))
    return out
