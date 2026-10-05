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
from typing import Any

from mosaic.core.keys import artifact_key
from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.media.ffmpeg.render import AUDIO_RATE, SEEK_MARGIN, Piece

RENDER_VERSION = "render/2"  # MOV chunks, phase-exact nearest-frame conform


@dataclass(frozen=True)
class Profile:
    kind: str  # preview|final
    width: int
    height: int
    encoder: str
    bitrate: str
    lossless: bool = False

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
        }


def profile(kind: str, encoders: list[str], lossless: bool = False) -> Profile:
    """Preview 720p from proxies; final 1080p SDR from originals (M0 defaults). The encoder
    is the first available of VideoToolbox → NVENC → openh264; FFV1 for lossless tests."""
    if not lossless and not encoders:
        raise RuntimeError("no H.264 encoder available in this FFmpeg build")
    enc = "ffv1" if lossless else encoders[0]
    if kind == "preview":
        return Profile("preview", 1280, 720, enc, "5M", lossless)
    return Profile("final", 1920, 1080, enc, "14M", lossless)


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
