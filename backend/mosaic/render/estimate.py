"""S19's export estimates (ADR 0091): each preset's file size and render time at each
resolution, and whether its codec can be encoded here. Display values only: sizes come
from the final profiles' bitrates, times from this computer's benchmark."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from mosaic.core.time import parse_rational
from mosaic.render.plan import CODECS, H264_BITRATE, HEVC_BITRATE, SHORT_SIDE, frame_size

# ProRes 422 at 29.97 fps (Apple's published data rates), scaled by pixels and frame rate.
PRORES_1080_BPS = 147_000_000
AAC_BPS = 192_000  # MP4 audio (media/ffmpeg/render.py)
PCM_BPS = 48_000 * 16 * 2  # MOV audio: 16-bit stereo PCM
REFERENCE = 1280 * 720  # the benchmark's 720p proxy


def _bps(value: str) -> int:
    return int(value.rstrip("M")) * 1_000_000


def video_bps(codec: str, resolution: str, aspect: str, rate: Fraction) -> int:
    if codec == "h264":
        return _bps(H264_BITRATE[resolution])
    if codec == "hevc":
        return _bps(HEVC_BITRATE[resolution])
    w, h = frame_size(aspect, SHORT_SIDE[resolution])
    return round(PRORES_1080_BPS * Fraction(w * h, 1920 * 1080) * rate / Fraction(30000, 1001))


def estimate(
    duration_frames: int,
    rate: str,
    aspect: str,
    working: dict[str, list[str]],
    ms_per_minute_720: int | None,
) -> dict[str, Any]:
    """Each codec's availability and, per resolution, its bytes and seconds (``None``
    without a benchmark)."""
    fps = parse_rational(rate)
    seconds = Fraction(duration_frames) / fps
    out: dict[str, Any] = {}
    for codec in CODECS:
        encoders = working.get(codec, [])
        sizes: dict[str, int] = {}
        times: dict[str, int | None] = {}
        for res in SHORT_SIDE:
            audio = PCM_BPS if codec == "prores" else AAC_BPS
            sizes[res] = round((video_bps(codec, res, aspect, fps) + audio) * seconds / 8)
            if ms_per_minute_720 is None:
                times[res] = None
            else:
                # Decoding the originals costs about the benchmark's pass; encoding grows
                # with the frame (a coarse guide, shown as "≈").
                w, h = frame_size(aspect, SHORT_SIDE[res])
                factor = 2 + Fraction(w * h, REFERENCE) / 2
                times[res] = round(seconds / 60 * ms_per_minute_720 / 1000 * factor)
        out[codec] = {
            "available": bool(encoders),
            "encoder": encoders[0] if encoders else None,
            "reason": None if encoders else f"No {codec.upper()} encoder works on this computer.",
            "bytes": sizes,
            "seconds": times,
        }
    return out
