"""ffprobe → typed ``ProbeResult`` (ARCHITECTURE.md §8 stage 1).

Raw ffprobe JSON is kept as an artifact blob by the caller (ADR 0002 G). Everything parsed
here is exact: time bases and rates are rationals, timestamps are integer ticks. Decimal
second strings from ffprobe are converted with ``Fraction(str)`` and never stored.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import FFmpegError, run

HFR_THRESHOLD = Fraction(100)


@dataclass(frozen=True)
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str | None
    codec_tag: str | None
    profile: str | None
    time_base: Fraction
    start_pts: int
    duration_ts: int | None
    nb_frames: int | None
    width: int | None = None
    height: int | None = None
    rate: Fraction | None = None
    avg_rate: Fraction | None = None
    rotation: int = 0
    pix_fmt: str | None = None
    bit_depth: int | None = None
    color_range: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    color_space: str | None = None
    dovi: bool = False
    channels: int | None = None
    channel_layout: str | None = None
    sample_rate: int | None = None
    handler: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    attached_pic: bool = False

    @property
    def is_video(self) -> bool:
        return self.codec_type == "video" and not self.attached_pic

    @property
    def is_audio(self) -> bool:
        return self.codec_type == "audio"

    @property
    def maybe_vfr(self) -> bool:
        return self.rate is not None and self.avg_rate is not None and self.rate != self.avg_rate


@dataclass(frozen=True)
class ProbeResult:
    format_name: str
    duration: Fraction | None  # exact, transient: from ffprobe's decimal string
    bit_rate: int | None
    tags: dict[str, str]
    streams: tuple[StreamInfo, ...]

    @property
    def video_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.is_video]

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.is_audio]

    def tag(self, *names: str) -> str | None:
        lower = {k.lower(): v for k, v in self.tags.items()}
        for name in names:
            v = lower.get(name.lower())
            if v:
                return v
        return None


class ProbeError(RuntimeError):
    pass


def _rational(value: Any) -> Fraction | None:
    if not value or not isinstance(value, str):
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            if int(den) == 0 or int(num) == 0:
                return None
            return Fraction(int(num), int(den))
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "N/A":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bit_depth(pix_fmt: str | None, raw: Any) -> int | None:
    explicit = _int(raw)
    if explicit:
        return explicit
    if not pix_fmt:
        return None
    semi = re.match(r"^p0(\d{2})", pix_fmt)  # p010le, p016le (VideoToolbox, NV12-style)
    if semi:
        return int(semi.group(1))
    m = re.search(r"p(\d{2})(le|be)?$", pix_fmt)
    if m:
        return int(m.group(1))
    return 8


def _rotation(stream: dict[str, Any]) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                return round(float(sd["rotation"])) % 360
            except (TypeError, ValueError):
                return 0
    tag = stream.get("tags", {}).get("rotate")
    return int(tag) % 360 if tag and str(tag).lstrip("-").isdigit() else 0


def parse_stream(s: dict[str, Any]) -> StreamInfo:
    tb = _rational(s.get("time_base"))
    if tb is None:
        raise ProbeError(f"stream {s.get('index')} has no time base")
    side = [sd.get("side_data_type", "") for sd in s.get("side_data_list", []) or []]
    tags = {str(k): str(v) for k, v in (s.get("tags") or {}).items()}
    handler = tags.get("handler_name")
    pix_fmt = s.get("pix_fmt")
    return StreamInfo(
        index=int(s["index"]),
        codec_type=str(s.get("codec_type", "unknown")),
        codec_name=s.get("codec_name"),
        codec_tag=s.get("codec_tag_string"),
        profile=s.get("profile"),
        time_base=tb,
        start_pts=_int(s.get("start_pts")) or 0,
        duration_ts=_int(s.get("duration_ts")),
        nb_frames=_int(s.get("nb_frames")),
        width=_int(s.get("width")),
        height=_int(s.get("height")),
        rate=_rational(s.get("r_frame_rate")),
        avg_rate=_rational(s.get("avg_frame_rate")),
        rotation=_rotation(s),
        pix_fmt=pix_fmt,
        bit_depth=_bit_depth(pix_fmt, s.get("bits_per_raw_sample")) if pix_fmt else None,
        color_range=s.get("color_range"),
        color_transfer=s.get("color_transfer"),
        color_primaries=s.get("color_primaries"),
        color_space=s.get("color_space"),
        dovi=any("DOVI" in x for x in side),
        channels=_int(s.get("channels")),
        channel_layout=s.get("channel_layout"),
        sample_rate=_int(s.get("sample_rate")),
        handler=handler.strip("\x0b ").strip() if handler else None,
        tags=tags,
        attached_pic=bool((s.get("disposition") or {}).get("attached_pic")),
    )


def parse_probe(data: dict[str, Any]) -> ProbeResult:
    fmt = data.get("format") or {}
    return ProbeResult(
        format_name=str(fmt.get("format_name", "")),
        duration=_rational(fmt.get("duration")),
        bit_rate=_int(fmt.get("bit_rate")),
        tags={str(k): str(v) for k, v in (fmt.get("tags") or {}).items()},
        streams=tuple(parse_stream(s) for s in data.get("streams", [])),
    )


def ffprobe(binaries: FFmpegBinaries, path: Path) -> dict[str, Any]:
    """Raw ffprobe JSON. Raises ``ProbeError`` with ffprobe's message on failure."""
    try:
        result = run(binaries, builders.ffprobe_json(path), timeout=120)
    except FFmpegError as exc:
        raise ProbeError(_summarize(exc.stderr)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("timed out reading the file") from exc
    try:
        data: dict[str, Any] = json.loads(result.stdout or b"{}")
    except ValueError as exc:
        raise ProbeError("unreadable probe output") from exc
    if not data.get("streams"):
        raise ProbeError("no streams found")
    return data


def decode_check(binaries: FFmpegBinaries, path: Path, stream: str = "v:0") -> str | None:
    """Decode the first frame; returns an error summary if the stream cannot be decoded."""
    try:
        run(binaries, builders.decode_first_frame(path, stream), timeout=120)
    except FFmpegError as exc:
        return _summarize(exc.stderr) or "the video stream could not be decoded"
    except subprocess.TimeoutExpired:
        return "decoding timed out"
    return None


def _summarize(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    if not lines:
        return "unreadable file"
    msg = lines[-1]
    msg = re.sub(r"^\[[^\]]+\]\s*", "", msg)
    return msg.split(": ", 1)[-1] if msg.startswith(("/", "file:")) else msg


def video_vfr_from_packets(binaries: FFmpegBinaries, path: Path, stream_index: int) -> bool:
    """True if packet durations really vary. On any error the stream is treated as VFR,
    the safe choice: PTS-based resampling handles CFR input too."""
    try:
        out = run(binaries, builders.ffprobe_packet_durations(path, stream_index), timeout=600)
    except (FFmpegError, OSError, subprocess.TimeoutExpired):
        return True
    histogram: dict[int, int] = {}
    for line in out.stdout.splitlines():
        d = _int(line.strip().rstrip(b",").decode() if line.strip() else None)
        if d:
            histogram[d] = histogram.get(d, 0) + 1
    return durations_vary_hist(histogram)


def durations_vary(raw: list[int | None]) -> bool:
    hist: dict[int, int] = {}
    for d in raw:
        if d:
            hist[d] = hist.get(d, 0) + 1
    return durations_vary_hist(hist)


def durations_vary_hist(hist: dict[int, int]) -> bool:
    """Compare the 1st and 99th percentile durations (outlier first/last packets ignored).

    CFR at NTSC rates in an integer timescale alternates by one tick (1501/1502 at 1/90000
    for 59.94 fps), so a one-tick spread, or a spread under 1%, is rounding.
    """
    total = sum(hist.values())
    if total < 2:
        return False
    ordered = sorted(hist.items())

    def percentile(q: float) -> int:
        target = q * (total - 1)
        seen = 0
        for value, count in ordered:
            seen += count
            if seen > target:
                return value
        return ordered[-1][0]

    lo, hi, median = percentile(0.01), percentile(0.99), percentile(0.5)
    spread = hi - lo
    return spread > 1 and spread * 100 > median
