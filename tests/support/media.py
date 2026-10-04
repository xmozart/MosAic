"""Shared helpers for frame-accuracy tests on synthetic media."""

from __future__ import annotations

import bisect
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from mosaic.devtools import barcode
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run


def decode_barcodes(
    bins: FFmpegBinaries, path: Path, w: int, h: int
) -> list[barcode.Decoded | None]:
    """Decoded barcode (index and the quarter-turns needed to read it) per frame."""
    raw = run(bins, builders.extract_rgb_frames(path, w, h)).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w, 3)
    return [barcode.decode(f) for f in frames]


def luma_frame(bins: FFmpegBinaries, path: Path, w: int, h: int, frame: int = 0) -> np.ndarray:
    raw = run(bins, builders.extract_luma(path, frame)).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w)


def cell_mean(luma: np.ndarray, row: int, col: int) -> float:
    """Mean luma at the centre of barcode cell (row, col) of an upright frame."""
    h, w = luma.shape
    bh = barcode.band_height(h)
    y0, y1 = row * bh // barcode.ROWS, (row + 1) * bh // barcode.ROWS
    x0, x1 = col * w // barcode.COLS, (col + 1) * w // barcode.COLS
    cy, cx = (y1 - y0) // 4, (x1 - x0) // 4
    return float(luma[y0 + cy : y1 - cy, x0 + cx : x1 - cx].mean())


def source_frame_times(bins: FFmpegBinaries, files: list[Path]) -> list[Fraction]:
    """Presentation times (seconds, relative to each file's first video PTS) of every
    source frame, concatenated across chapter files."""
    times: list[Fraction] = []
    offset = Fraction(0)
    for path in files:
        info = json.loads(run(bins, builders.ffprobe_json(path)).stdout)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        tb = Fraction(v["time_base"])
        data = json.loads(run(bins, builders.ffprobe_frames(path)).stdout)
        pts = sorted(int(f["pts"]) for f in data["frames"] if "pts" in f)
        first = pts[0]
        times += [offset + (p - first) * tb for p in pts]
        offset += int(v["duration_ts"]) * tb
    return times


def nearest_index(times: list[Fraction], t: Fraction) -> int:
    i = bisect.bisect_left(times, t)
    if i == 0:
        return 0
    if i >= len(times):
        return len(times) - 1
    return i if times[i] - t < t - times[i - 1] else i - 1
