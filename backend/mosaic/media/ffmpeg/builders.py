"""Typed builders for every FFmpeg/ffprobe invocation MosAic makes.

Each function returns an ``FFmpegCommand`` or ``ProbeCommand``; nothing outside
``mosaic.media.ffmpeg`` assembles argv lists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from mosaic.media.ffmpeg.command import (
    FFmpegCommand,
    Filter,
    InputSpec,
    OptionValue,
    OutputSpec,
    ProbeCommand,
    chain,
    escape_filter_value,
    media_path,
)

# --------------------------------------------------------------------------- probe


def ffprobe_json(path: Path) -> ProbeCommand:
    return ProbeCommand(
        args=[
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            media_path(path),
        ],
        description=f"probe {path.name}",
    )


def ffprobe_packets(path: Path, stream_index: int) -> ProbeCommand:
    """Packet PTS/duration list for one stream (used for VFR and tick maps)."""
    return ProbeCommand(
        args=[
            "-print_format",
            "json",
            "-select_streams",
            str(stream_index),
            "-show_entries",
            "packet=pts,dts,duration,flags",
            media_path(path),
        ],
        description=f"packets {path.name}#{stream_index}",
    )


def ffprobe_frames(path: Path, stream_spec: str = "v:0") -> ProbeCommand:
    return ProbeCommand(
        args=[
            "-print_format",
            "json",
            "-select_streams",
            stream_spec,
            "-show_entries",
            "frame=pts,duration,pict_type,key_frame",
            media_path(path),
        ],
        description=f"frames {path.name}",
    )


# --------------------------------------------------------------- synthetic media


@dataclass(frozen=True)
class ColorTags:
    primaries: str = "bt709"
    trc: str = "bt709"
    matrix: str = "bt709"
    range: str = "tv"  # tv | pc


@dataclass(frozen=True)
class LavfiAudio:
    """A generated audio input such as ``sine=frequency=440``."""

    graph: str
    layout: str = "stereo"


@dataclass(frozen=True)
class FileAudio:
    path: Path


AudioSource = LavfiAudio | FileAudio


@dataclass(frozen=True)
class VideoEncoding:
    codec: str
    pix_fmt: str
    options: tuple[tuple[str, OptionValue], ...] = ()
    tag: str | None = None


@dataclass
class SynthSpec:
    out: Path
    width: int
    height: int
    rate: Fraction
    frames: int
    encoding: VideoEncoding
    color: ColorTags = field(default_factory=ColorTags)
    audio: Sequence[AudioSource] = ()
    setpts_expr: str | None = None  # VFR timing, e.g. "(N/30+floor(N/3)/60)/TB"
    timescale: int = 90000
    fps_mode_passthrough: bool = False
    container: str | None = None  # explicit muxer, e.g. "mp4" for camera ".LRF" files


def synth_from_rawvideo(spec: SynthSpec) -> FFmpegCommand:
    """Encode raw RGB frames from stdin, plus optional audio, into a tagged file."""
    inputs = [
        InputSpec(
            "pipe:0",
            [
                ("-f", "rawvideo"),
                ("-pix_fmt", "rgb24"),
                ("-s", f"{spec.width}x{spec.height}"),
                ("-framerate", spec.rate),
            ],
        )
    ]
    for audio in spec.audio:
        if isinstance(audio, LavfiAudio):
            inputs.append(InputSpec(audio.graph, [("-f", "lavfi")]))
        else:
            inputs.append(InputSpec(media_path(audio.path), [("-stream_loop", "-1")]))

    matrix = "bt2020" if spec.color.matrix.startswith("bt2020") else spec.color.matrix
    vfilters = [
        Filter.of("scale", out_color_matrix=matrix, out_range=spec.color.range),
        Filter.of("format", spec.encoding.pix_fmt),
        Filter.of(
            "setparams",
            color_primaries=spec.color.primaries,
            color_trc=spec.color.trc,
            colorspace=spec.color.matrix,
            range=spec.color.range,
        ),
    ]
    if spec.setpts_expr:
        vfilters.append(Filter.of("setpts", escape_filter_value(spec.setpts_expr)))

    opts: list[tuple[str, OptionValue]] = [("-map", "0:v:0")]
    for i in range(len(spec.audio)):
        opts.append(("-map", f"{i + 1}:a:0"))
    opts += [("-vf", chain(*vfilters)), ("-c:v", spec.encoding.codec)]
    opts += list(spec.encoding.options)
    if spec.encoding.tag:
        opts.append(("-tag:v", spec.encoding.tag))
    opts += [
        ("-color_primaries", spec.color.primaries),
        ("-color_trc", spec.color.trc),
        ("-colorspace", spec.color.matrix),
        ("-color_range", spec.color.range),
        ("-video_track_timescale", spec.timescale),
    ]
    if spec.fps_mode_passthrough:
        opts.append(("-fps_mode", "passthrough"))
    if spec.audio:
        opts += [("-c:a", "aac"), ("-b:a", "128k"), ("-ar", 48000)]
        opts.append(("-shortest", None))
    opts += [("-movflags", "+faststart")]
    if spec.container:
        opts.append(("-f", spec.container))
    return FFmpegCommand(
        inputs=inputs,
        outputs=[OutputSpec(media_path(spec.out), opts)],
        description=f"synth {spec.out.name}",
    )


def _seconds_arg(value: Fraction) -> str:
    """Render an exact duration as integral microseconds (FFmpeg duration syntax)."""
    return f"{round(value * 1_000_000)}us"


def remux(
    src: Path,
    out: Path,
    *,
    display_rotation: int | None = None,
    output_ts_offset: Fraction | None = None,
    video_bsf: str | None = None,
) -> FFmpegCommand:
    in_opts: list[tuple[str, OptionValue]] = []
    if display_rotation is not None:
        in_opts.append(("-display_rotation:v:0", display_rotation))
    out_opts: list[tuple[str, OptionValue]] = [("-map", "0"), ("-c", "copy")]
    if output_ts_offset is not None:
        out_opts.append(("-output_ts_offset", _seconds_arg(output_ts_offset)))
    if video_bsf:
        out_opts.append(("-bsf:v", video_bsf))
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src), in_opts)],
        outputs=[OutputSpec(media_path(out), out_opts)],
        description=f"remux {out.name}",
    )


# ----------------------------------------------------------- frame extraction


def extract_rgb_frames(src: Path, width: int, height: int) -> FFmpegCommand:
    """Decode every frame (display-rotated, no rate conversion) as packed RGB to stdout."""
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src))],
        outputs=[
            OutputSpec(
                "pipe:1",
                [
                    ("-map", "0:v:0"),
                    ("-vf", chain(Filter.of("scale", w=width, h=height, flags="area"))),
                    ("-fps_mode", "passthrough"),
                    ("-f", "rawvideo"),
                    ("-pix_fmt", "rgb24"),
                ],
            )
        ],
        description=f"rgb frames {src.name}",
    )
