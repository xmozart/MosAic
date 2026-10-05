"""Frame-accuracy check of a render against its edit (M0 acceptance 1, ADR 0002 E).

Every synthetic corpus frame carries a barcode of its source frame index. For each event,
each output frame ``k`` should show the source frame nearest to
``source_in + k / timeline_rate``: for CFR sources that is ``round(t · source_rate)``; for
VFR sources the frame whose PTS is nearest ``t`` (from the tick map's PTS table, given as
``pts_seconds``). Errors are reported per event; ±1 frame passes.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from mosaic.core.time import parse_rational
from mosaic.devtools.barcode import decode
from mosaic.media.ffmpeg.builders import raw_frames
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import stream_stdout


@dataclass
class EventCheck:
    event_id: str
    asset_id: str
    frames: int
    decoded: int = 0
    worst: int = 0
    errors: dict[int, int] = field(default_factory=dict)  # error → count

    @property
    def ok(self) -> bool:
        return self.decoded == self.frames and self.worst <= 1


DECODE_W, DECODE_H = 640, 360  # renders are 16:9; barcodes decode fine at this size


def frames_of(binaries: FFmpegBinaries, path: Path) -> Iterator[np.ndarray]:
    """Gray frames of a render at the decode size, one at a time (bounded memory)."""
    size = DECODE_W * DECODE_H
    for data in stream_stdout(binaries, raw_frames(path, DECODE_W, DECODE_H, "gray"), size):
        if len(data) == size:
            yield np.frombuffer(data, np.uint8).reshape(DECODE_H, DECODE_W)


def content_rect(display_w: int, display_h: int) -> tuple[int, int, int, int]:
    """Where a source of this display size sits on the 16:9 canvas (pillar/letterbox)."""
    scale = min(Fraction(DECODE_W, display_w), Fraction(DECODE_H, display_h))
    w, h = int(display_w * scale), int(display_h * scale)
    return (DECODE_W - w) // 2, (DECODE_H - h) // 2, w, h


def expected_index(
    t: Fraction, source_rate: Fraction | None, pts_seconds: list[Fraction] | None
) -> int:
    if pts_seconds:
        i = bisect.bisect_left(pts_seconds, t)
        options = [j for j in (i - 1, i) if 0 <= j < len(pts_seconds)]
        return min(options, key=lambda j: (abs(pts_seconds[j] - t), j))
    assert source_rate is not None
    return round(t * source_rate)


@dataclass(frozen=True)
class SourceInfo:
    rate: Fraction | None  # CFR source rate (None for VFR)
    pts: list[Fraction] | None  # VFR: each source frame's PTS in seconds from logical 0
    offset: int  # barcode index of the asset's first frame
    display: tuple[int, int]  # display width, height (after rotation)


def check_render(
    binaries: FFmpegBinaries, path: Path, timeline: dict[str, Any], sources: dict[str, SourceInfo]
) -> list[EventCheck]:
    """Per event, how far each frame's barcode is from the expected source frame."""
    rate = parse_rational(timeline["rate"])
    events = timeline["tracks"][0]["events"]
    bounds = [(e["timeline_in"]["frames"], e["timeline_out"]["frames"]) for e in events]
    checks = [
        EventCheck(e["event_id"], e["asset_id"], b - a)
        for e, (a, b) in zip(events, bounds, strict=True)
    ]
    ev = 0
    for n, frame in enumerate(frames_of(binaries, path)):
        while ev < len(events) and n >= bounds[ev][1]:
            ev += 1
        if ev >= len(events):
            break
        e = events[ev]
        k = n - bounds[ev][0]
        src = sources[e["asset_id"]]
        tb = parse_rational(e["source_in"]["tb"])
        t = Fraction(e["source_in"]["ticks"]) * tb + Fraction(k) / rate
        want = expected_index(t, src.rate, src.pts) + src.offset
        d = decode(frame, content_rect(*src.display))
        if d is None:
            continue
        c = checks[ev]
        c.decoded += 1
        err = d.index - want
        c.errors[err] = c.errors.get(err, 0) + 1
        c.worst = max(c.worst, abs(err))
    return checks
