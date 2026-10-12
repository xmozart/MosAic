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
from mosaic.core.time import Rounding, frame_start_ticks, parse_rational, round_fraction
from mosaic.media.ffmpeg.render import AUDIO_RATE, SEEK_MARGIN, Piece

Fill = Literal["auto", "crop"]
Framing = Literal["fit", "crop"]
RENDER_VERSION = "render/3"  # aspect framing: crop near the target shape, else fit (ADR 0046)
STILL_VERSION = "still/1"  # canvas, blurred fill and pan/zoom (ADR 0075)
# An event's own audio window (a J- or L-cut, ADR 0077).
AUDIO_WINDOW = ("source_in", "source_out", "timeline_in", "timeline_out")
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
            # A J- or L-cut's audio window is the audio chunk's (``audio_key``): left out,
            # so a split event's picture is reused wherever it sits (ADR 0077).
            "audio": {k: v for k, v in event["audio"].items() if k not in AUDIO_WINDOW},
            "transform": event.get("transform"),
            "speed": event.get("speed"),
            **dips(event),
        },
        config={"profile": prof.as_json(), "rate": rate},
        version=RENDER_VERSION,
    )


def parse_rate(rate: str) -> Fraction:
    return parse_rational(rate)


def still_key(project_id: str, event: dict[str, Any], photo: str, prof: Profile, rate: str) -> str:
    """A still chunk's key (ADR 0075): the photo's fingerprint, its frames and motion,
    and the profile."""
    return artifact_key(
        "still",
        project_id=project_id,
        inputs={
            "photo": photo,
            "asset": event["asset_id"],
            "frames": event["timeline_out"]["frames"] - event["timeline_in"]["frames"],
            "motion": event.get("motion"),
            **dips(event),
        },
        config={"profile": prof.as_json(), "rate": rate, "still": STILL_VERSION},
        version=RENDER_VERSION,
    )


AUDIO_VERSION = "audio/1"  # separate audio chunks for J- and L-cuts (ADR 0077)
TRANSITION_VERSION = "transition/1"  # dissolves as xfade chunks, dips as fades (ADR 0078)


def is_split(timeline: dict[str, Any]) -> bool:
    """Whether any event's sound has its own window (a J- or L-cut, ADR 0077)."""
    return any("timeline_in" in e["audio"] for e in timeline["tracks"][0]["events"])


def audio_span(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], int]:
    """An event's heard source range and its length in timeline frames."""
    a = event["audio"]
    w = a if "timeline_in" in a else event
    return w["source_in"], w["source_out"], w["timeline_out"]["frames"] - w["timeline_in"]["frames"]


def audio_key(
    project_id: str, event: dict[str, Any], sources: list[str], prof: Profile, rate: str
) -> str:
    """An audio chunk's key (ADR 0077): the event's heard window, its audio settings, its
    sources and the profile (previews read the proxies' audio)."""
    src_in, src_out, frames = audio_span(event)
    a = event["audio"]
    return artifact_key(
        "audio",
        project_id=project_id,
        inputs={
            "sources": sources,
            "asset": event["asset_id"],
            "kind": event.get("kind", "video"),
            "in": src_in,
            "out": src_out,
            "frames": frames,
            "audio": {
                k: a[k] for k in ("source_enabled", "gain_db", "fade_in_frames", "fade_out_frames")
            },
            **dips(event),
        },
        config={"profile": prof.kind, "rate": rate, "audio": AUDIO_VERSION},
        version=RENDER_VERSION,
    )


# ------------------------------------------------------------------ transitions
# ADR 0078: a dip is a fade inside its event's chunk; a dissolve of D frames is its own
# chunk, centred on the cut, so the pictures either side are D/2 frames shorter and the
# dissolve chunk blends D/2 frames of each past the cut (handles the refiner checked).


def _transition(event: dict[str, Any], side: str, kind: str) -> int:
    t = event.get(side) or {}
    return int(t["frames"]) if t.get("type") == kind else 0


def dissolve_frames(event: dict[str, Any]) -> int:
    """Frames of the dissolve from this event into the next (0: none)."""
    return _transition(event, "transition_out", "dissolve")


def dips(event: dict[str, Any]) -> dict[str, int]:
    """An event's fades from and to black, for its chunk key (nothing without one, so
    events without a dip keep their keys)."""
    d_in = _transition(event, "transition_in", "dip")
    d_out = _transition(event, "transition_out", "dip")
    return {k: v for k, v in (("dip_in", d_in), ("dip_out", d_out)) if v}


def fades(event: dict[str, Any], rate: str) -> tuple[Fraction, Fraction]:
    """An event's sound fades in seconds: its own, or its dip's when longer (a dip to
    black takes the sound with it)."""
    a = event["audio"]
    d = dips(event)
    r = parse_rational(rate)
    return (
        Fraction(max(int(a["fade_in_frames"]), d.get("dip_in", 0))) / r,
        Fraction(max(int(a["fade_out_frames"]), d.get("dip_out", 0))) / r,
    )


def _window(event: dict[str, Any], start: int, frames: int, rate: str) -> dict[str, Any]:
    """``event`` cut to ``frames`` frames starting ``start`` frames after its own start
    (negative: before it, into the handle)."""
    tb = event["source_in"]["tb"]
    s0 = event["source_in"]["ticks"]
    a = (
        s0 + frame_start_ticks(start, rate, tb)
        if start >= 0
        else s0 - frame_start_ticks(-start, rate, tb)
    )
    b = s0 + frame_start_ticks(start + frames, rate, tb)
    t0 = event["timeline_in"]["frames"] + start
    return event | {
        "source_in": {"ticks": a, "tb": tb},
        "source_out": {"ticks": b, "tb": tb},
        "timeline_in": {"frames": t0, "rate": rate},
        "timeline_out": {"frames": t0 + frames, "rate": rate},
    }


def picture(timeline: dict[str, Any], index: int) -> dict[str, Any]:
    """The part of event ``index`` its own chunk renders: the event less half of each
    dissolve it takes part in. Where a dissolve takes over, its sound is not faded."""
    events = timeline["tracks"][0]["events"]
    e = events[index]
    head = dissolve_frames(events[index - 1]) // 2 if index else 0
    tail = dissolve_frames(e) // 2
    if not head and not tail:
        return dict(e)
    frames = e["timeline_out"]["frames"] - e["timeline_in"]["frames"]
    out = _window(e, head, frames - head - tail, timeline["rate"])
    audio = dict(e["audio"])
    if head:
        audio["fade_in_frames"] = 0
    if tail:
        audio["fade_out_frames"] = 0
    out["audio"] = audio
    return out


def dissolve_sides(
    timeline: dict[str, Any], index: int
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """The two pictures a dissolve from event ``index`` into the next blends, each the
    dissolve's frames long and centred on the cut, with the outgoing sound fading out
    and the incoming one fading in over it."""
    events = timeline["tracks"][0]["events"]
    a, b = events[index], events[index + 1]
    n = dissolve_frames(a)
    if n % 2:
        raise ValueError(f"{a['event_id']}: a dissolve has an even number of frames")
    half = n // 2
    rate = timeline["rate"]
    frames_a = a["timeline_out"]["frames"] - a["timeline_in"]["frames"]
    side_a = _window(a, frames_a - half, n, rate)
    # The handle past the out point is what the refiner checked: from the out point itself.
    tb_a = a["source_out"]["tb"]
    side_a["source_out"] = {
        "ticks": a["source_out"]["ticks"] + frame_start_ticks(half, rate, tb_a),
        "tb": tb_a,
    }
    side_b = _window(b, -half, n, rate)
    side_a["audio"] = dict(a["audio"]) | {"fade_in_frames": 0, "fade_out_frames": n}
    side_b["audio"] = dict(b["audio"]) | {"fade_in_frames": n, "fade_out_frames": 0}
    for side in (side_a, side_b):
        side.pop("transition_in", None)
        side["transition_out"] = {"type": "cut"}
    return side_a, side_b, n


def dissolve_key(project_id: str, key_a: str, key_b: str, frames: int, rate: str) -> str:
    """A dissolve chunk's key: the keys of the two pictures it blends."""
    return artifact_key(
        "dissolve",
        project_id=project_id,
        inputs={"a": key_a, "b": key_b, "frames": frames},
        config={"rate": rate, "transition": TRANSITION_VERSION},
        version=RENDER_VERSION,
    )
