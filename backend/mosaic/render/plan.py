"""Render planning: timeline events → chunk specs (ARCHITECTURE.md §10), pure functions.

An event's source range is in logical asset ticks. ``pieces`` maps it onto the files that
hold it: chapter ``i`` covers logical ``[L_i, L_i + D_i)`` and its logical 0 is the first
video PTS of that file, so absolute stream seconds are ``video_start_i + (t - L_i)·tb``.
Previews read the proxy instead, whose time 0 is logical 0.

A chunk's audio is ``round(frames · 48000 / rate)`` samples, which depends only on the
chunk itself, so an unchanged event's chunk is reused across versions (§10). The rounding
is under half a sample per chunk; the assembler pads or trims the total to the edit's
exact length.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from mosaic.core.keys import artifact_key
from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.media.ffmpeg.render import AUDIO_RATE, SEEK_MARGIN, Piece

Fill = Literal["auto", "crop"]
Framing = Literal["fit", "crop"]
RENDER_VERSION = "render/3"  # aspect framing: crop near the target shape, else fit (ADR 0046)
ASPECTS = {
    "16:9": Fraction(16, 9),
    "9:16": Fraction(9, 16),
    "4:5": Fraction(4, 5),
    "1:1": Fraction(1),
    "2.39:1": Fraction(239, 100),
}
SHORT_SIDE = {"720p": 720, "1080p": 1080, "1440p": 1440, "4k": 2160}
PREVIEW_SHORT_SIDE = 720
MAX_LONG_SIDE = 4096  # H.264 level 5.2 and NVENC's widest frame
CROP_WITHIN = Fraction(5, 4)  # a clip within 25 % of the target's shape fills it by cropping


@dataclass(frozen=True)
class Profile:
    kind: str  # preview|final
    width: int
    height: int
    encoder: str
    bitrate: str
    lossless: bool = False
    # "crop": the edit's shape is not its footage's (a 9:16 reel from landscape clips):
    # every clip fills the frame by a centre crop. "auto": ``framing`` decides per clip.
    fill: Fill = "auto"

    @property
    def container(self) -> str:
        return "mov" if self.lossless else "mp4"

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "encoder": self.encoder,
            "bitrate": self.bitrate,
            "lossless": self.lossless,
            "fill": self.fill,
        }


def frame_size(aspect: str, short_side: int) -> tuple[int, int]:
    """Width and height (even) of ``aspect`` with ``short_side`` pixels on its short side:
    16:9 at 1080 → 1920×1080, 9:16 → 1080×1920, 4:5 → 1080×1350. The long side is capped
    at ``MAX_LONG_SIDE`` (the short side shrinks to keep the shape): 2.39:1 at 4K is
    4096×1714, within what every H.264 encoder takes (level 5.2, NVENC's 4096 px)."""
    ratio = ASPECTS[aspect]

    def even(x: Fraction) -> int:
        return 2 * round(x / 2)

    long_side = short_side * (ratio if ratio >= 1 else 1 / ratio)
    if long_side > MAX_LONG_SIDE:
        long_side, short = (
            Fraction(MAX_LONG_SIDE),
            MAX_LONG_SIDE / (ratio if ratio >= 1 else 1 / ratio),
        )
    else:
        short = Fraction(short_side)
    if ratio >= 1:
        return even(long_side), even(short)
    return even(short), even(long_side)


def profile(
    kind: str,
    encoders: list[str],
    lossless: bool = False,
    aspect: str = "16:9",
    resolution: str = "1080p",
    native: Fraction | None = None,
) -> Profile:
    """Preview 720p from proxies; final at ``resolution`` (default 1080p) SDR from
    originals, both in the edit's ``aspect`` (ADR 0046). ``native`` is the shape of the
    edit's footage (``dominant_shape``): an aspect far from it crops every clip. The
    encoder is the first available of VideoToolbox → NVENC → openh264; FFV1 for lossless
    tests."""
    if not lossless and not encoders:
        raise RuntimeError("no H.264 encoder available in this FFmpeg build")
    enc = "ffv1" if lossless else encoders[0]
    fill: Fill = "crop" if native is not None and not _close(native, ASPECTS[aspect]) else "auto"
    if kind == "preview":
        w, h = frame_size(aspect, PREVIEW_SHORT_SIDE)
        return Profile("preview", w, h, enc, "5M", lossless, fill)
    w, h = frame_size(aspect, SHORT_SIDE[resolution])
    bitrate = {"720p": "8M", "1080p": "14M", "1440p": "24M", "4k": "45M"}[resolution]
    return Profile("final", w, h, enc, bitrate, lossless, fill)


def _close(a: Fraction, b: Fraction) -> bool:
    return (a / b if a >= b else b / a) <= CROP_WITHIN


def dominant_shape(clips: list[tuple[int | None, int | None, int]]) -> Fraction | None:
    """The display shape covering most of the edit: ``(width, height, frames)`` per event.
    None when no clip has a known size."""
    totals: dict[Fraction, int] = {}
    for w, h, frames in clips:
        if w and h:
            shape = Fraction(w, h)
            totals[shape] = totals.get(shape, 0) + frames
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: (kv[1], kv[0]))[0]


def framing(
    display_w: int | None, display_h: int | None, width: int, height: int, fill: str = "auto"
) -> Framing:
    """How a clip fills the frame (PRODUCT.md §4 Destination, ADR 0046): ``crop`` (a
    centre crop) when the profile crops everything or the clip's shape is within 25 % of
    the frame's; else ``fit`` (scaled in whole, with bars), so a portrait phone clip in a
    landscape edit of landscape footage stays visible."""
    if fill == "crop":
        return "crop"
    if not display_w or not display_h:
        return "fit"
    return "crop" if _close(Fraction(display_w, display_h), Fraction(width, height)) else "fit"


@dataclass(frozen=True)
class SourceFile:
    path: Path
    logical_start: int  # asset ticks
    duration: int  # asset ticks
    video_start: Fraction  # seconds: the file's first video PTS
    fingerprint: str


def pieces(
    src_in: int,
    src_out: int,
    tb: Fraction,
    files: list[SourceFile],
    frame: Fraction = Fraction(1, 30),
) -> list[Piece]:
    """``frame`` is one source frame in seconds (used only past the end of the media)."""
    out: list[Piece] = []
    for f in files:
        a = max(src_in, f.logical_start)
        b = min(src_out, f.logical_start + f.duration)
        if b <= a:
            continue
        local_a = Fraction(a - f.logical_start) * tb
        local_b = Fraction(b - f.logical_start) * tb
        out.append(
            Piece(
                path=f.path,
                start=f.video_start + local_a,
                end=f.video_start + local_b,
                seek=max(Fraction(0), local_a - SEEK_MARGIN),
            )
        )
    if not out and files:
        # Past the end of the last file (rounding at the very end): its last frame, so the
        # chunk is never empty (tpad then holds it for the event's length).
        f = files[-1]
        local = Fraction(f.duration) * tb
        start = max(Fraction(0), local - frame)
        out.append(
            Piece(
                f.path,
                f.video_start + start,
                f.video_start + local,
                max(Fraction(0), start - SEEK_MARGIN),
            )
        )
    return out


def samples_for(frames: int, rate: Fraction) -> int:
    return round_fraction(Fraction(frames) * AUDIO_RATE / rate, Rounding.NEAREST)


def chunk_key(
    project_id: str,
    event: dict[str, Any],
    sources: list[str],
    prof: Profile,
    rate: str,
) -> str:
    return artifact_key(
        "chunk",
        project_id=project_id,
        inputs={
            "sources": sources,
            "asset": event["asset_id"],
            "in": event["source_in"],
            "out": event["source_out"],
            "frames": event["timeline_out"]["frames"] - event["timeline_in"]["frames"],
            "audio": event["audio"],
            "transform": event.get("transform"),
            "speed": event.get("speed"),
        },
        config={"profile": prof.as_json(), "rate": rate},
        version=RENDER_VERSION,
    )


def parse_rate(rate: str) -> Fraction:
    return parse_rational(rate)
