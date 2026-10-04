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


def decode_first_frame(src: Path, stream: str = "v:0") -> FFmpegCommand:
    """Decode one frame of ``stream`` to the null muxer (decodability check)."""
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src))],
        outputs=[
            OutputSpec(
                "-",
                [("-map", f"0:{stream}"), ("-frames:v", 1), ("-f", "null")],
            )
        ],
        description=f"decode check {src.name}",
    )


def ffprobe_packet_durations(path: Path, stream_index: int) -> ProbeCommand:
    """One packet duration per line (compact CSV, no per-packet JSON objects)."""
    return ProbeCommand(
        args=[
            "-select_streams",
            str(stream_index),
            "-show_entries",
            "packet=duration",
            "-of",
            "csv=p=0",
            media_path(path),
        ],
        description=f"packet durations {path.name}#{stream_index}",
    )


# --------------------------------------------------------------------- proxies

TONEMAP_TO_SDR: tuple[Filter, ...] = (
    Filter.of("format", "yuv420p10le"),
    Filter.of("zscale", t="linear", npl=100),
    Filter.of("format", "gbrpf32le"),
    Filter.of("zscale", p="bt709"),
    Filter.of("tonemap", tonemap="hable", desat=0),
    Filter.of("zscale", t="bt709", m="bt709", r="tv"),
)
"""HLG/PQ → SDR Rec.709 (ARCHITECTURE.md §10): zscale + tonemap."""


def seconds_expr(value: Fraction) -> str:
    """An exact-enough decimal for an FFmpeg expression (microsecond precision)."""
    return f"{float(value):.6f}"


@dataclass
class ProxySpec:
    inputs: list[Path]  # chapter files in order
    video_index: int
    audio_index: int | None
    width: int
    height: int
    rate: Fraction
    hdr: str | None  # "hlg" | "pq" | None
    full_range: bool
    encoder: str
    bitrate: str
    video_starts: list[Fraction] = field(default_factory=list)  # per input, seconds
    video_durations: list[Fraction] = field(default_factory=list)  # per input, seconds
    hwaccel: str | None = None
    out: Path | None = None


def proxy(spec: ProxySpec) -> FFmpegCommand:
    """720p CFR H.264 SDR proxy over the concatenated chapters (ARCHITECTURE.md §8)."""
    if spec.out is None:
        raise ValueError("ProxySpec.out is not set")
    n = len(spec.inputs)
    inputs: list[InputSpec] = []
    for path in spec.inputs:
        opts: list[tuple[str, OptionValue]] = []
        if spec.hwaccel:
            opts.append(("-hwaccel", spec.hwaccel))
        inputs.append(InputSpec(media_path(path), opts))

    chains: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []
    for i in range(n):
        chains.append(f"[{i}:{spec.video_index}]setpts=PTS-STARTPTS[v{i}]")
        vlabels.append(f"[v{i}]")
        if spec.audio_index is not None:
            start = spec.video_starts[i] if i < len(spec.video_starts) else Fraction(0)
            afilters = [
                Filter.of("asetpts", f"PTS-{seconds_expr(start)}/TB"),
                Filter.of("aresample", "48000", **{"async": 1, "first_pts": 0}),
                Filter.of("aformat", sample_fmts="fltp", channel_layouts="stereo"),
            ]
            if i < len(spec.video_durations):
                # Pin each chapter's audio to its video length so A/V cannot drift
                # across chapter boundaries.
                dur = seconds_expr(spec.video_durations[i])
                afilters += [Filter.of("apad", whole_dur=dur), Filter.of("atrim", end=dur)]
            achain = chain(*afilters)
            chains.append(f"[{i}:{spec.audio_index}]{achain}[a{i}]")
            alabels.append(f"[a{i}]")
    if n > 1:
        chains.append("".join(vlabels) + f"concat=n={n}:v=1:a=0[vc]")
        if alabels:
            chains.append("".join(alabels) + f"concat=n={n}:v=0:a=1[ac]")
        vin, ain = "[vc]", "[ac]"
    else:
        vin, ain = "[v0]", "[a0]"

    vfilters: list[Filter] = [
        Filter.of(
            "scale",
            w=spec.width,
            h=spec.height,
            flags="bicubic",
            in_range="pc" if spec.full_range else "tv",
            out_range="tv",
            out_color_matrix="bt709",
        )
        if not spec.hdr
        else Filter.of("scale", w=spec.width, h=spec.height, flags="bicubic"),
    ]
    if spec.hdr:
        vfilters += list(TONEMAP_TO_SDR)
    vfilters += [
        Filter.of("setsar", "1"),
        Filter.of("fps", fps=spec.rate, round="near"),
        Filter.of("format", "yuv420p"),
        Filter.of(
            "setparams", color_primaries="bt709", color_trc="bt709", colorspace="bt709", range="tv"
        ),
    ]
    chains.append(f"{vin}{chain(*vfilters)}[vout]")

    gop = max(1, round(spec.rate * 2))
    out_opts: list[tuple[str, OptionValue]] = [
        ("-map", "[vout]"),
        ("-c:v", spec.encoder),
        ("-b:v", spec.bitrate),
        ("-g", gop),
        ("-color_primaries", "bt709"),
        ("-color_trc", "bt709"),
        ("-colorspace", "bt709"),
        ("-color_range", "tv"),
        ("-video_track_timescale", spec.rate.numerator),
    ]
    if spec.audio_index is not None:
        out_opts += [("-map", ain), ("-c:a", "aac"), ("-b:a", "128k"), ("-ar", 48000)]
    out_opts += [("-movflags", "+faststart"), ("-f", "mp4")]
    return FFmpegCommand(
        inputs=inputs,
        outputs=[OutputSpec(media_path(spec.out), out_opts)],
        # Raw input timestamps: the filters above rebase video and audio to the video
        # stream's first PTS themselves, which preserves A/V alignment.
        global_options=[("-copyts", None)],
        filter_complex=";".join(chains),
        description=f"proxy {spec.inputs[0].name}",
    )


def ffprobe_video_pts(path: Path, stream_index: int) -> ProbeCommand:
    """One packet PTS per line for a video stream (frame times, decode order)."""
    return ProbeCommand(
        args=[
            "-select_streams",
            str(stream_index),
            "-show_entries",
            "packet=pts",
            "-of",
            "csv=p=0",
            media_path(path),
        ],
        description=f"packet pts {path.name}#{stream_index}",
    )


def extract_luma(src: Path, frame: int = 0) -> FFmpegCommand:
    """Raw 8-bit luma plane of one frame, values untouched (range checks)."""
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src))],
        outputs=[
            OutputSpec(
                "pipe:1",
                [
                    ("-map", "0:v:0"),
                    (
                        "-vf",
                        chain(
                            Filter.of("trim", start_frame=frame, end_frame=frame + 1),
                            Filter.of("extractplanes", "y"),
                        ),
                    ),
                    ("-frames:v", 1),
                    ("-f", "rawvideo"),
                    ("-pix_fmt", "gray"),
                ],
            )
        ],
        description=f"luma {src.name}#{frame}",
    )


def raw_frames(src: Path, width: int, height: int, pix_fmt: str = "rgb24") -> FFmpegCommand:
    """Every frame of a (CFR, upright) proxy, scaled, as raw video on stdout."""
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
                    ("-pix_fmt", pix_fmt),
                ],
            )
        ],
        description=f"raw frames {src.name}",
    )


def select_frames(
    src: Path, frames: Sequence[int], rate: Fraction, pix_fmt: str = "rgb24"
) -> FFmpegCommand:
    """Selected frame indices of a CFR proxy at full size, in order, as raw video.

    Seeks to the first wanted frame, then selects by output frame number relative to it.
    """
    if not frames:
        raise ValueError("no frames selected")
    first = frames[0]
    rel = [f - first for f in frames]
    expr = "+".join(f"eq(n\\,{r})" for r in rel)
    # Floor to whole microseconds so the first wanted frame is never skipped by seeking.
    start_us = (Fraction(first) / rate * 1_000_000).__floor__()
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src), [("-ss", f"{start_us}us")])],
        outputs=[
            OutputSpec(
                "pipe:1",
                [
                    ("-map", "0:v:0"),
                    ("-vf", f"select={expr}"),
                    ("-fps_mode", "passthrough"),
                    ("-frames:v", len(frames)),
                    ("-f", "rawvideo"),
                    ("-pix_fmt", pix_fmt),
                ],
            )
        ],
        description=f"select {len(frames)} frames {src.name}",
    )


def audio_pcm(
    src: Path,
    rate: int,
    channels: int,
    *,
    start: Fraction | None = None,
    duration: Fraction | None = None,
) -> FFmpegCommand:
    """The first audio stream of ``src`` as float32 little-endian PCM on stdout.

    Used on proxies, whose audio is already aligned to the asset's logical time 0.
    """
    in_opts: list[tuple[str, OptionValue]] = []
    if start is not None:
        in_opts.append(("-ss", _seconds_arg(start)))
    out_opts: list[tuple[str, OptionValue]] = [("-map", "0:a:0")]
    if duration is not None:
        out_opts.append(("-t", _seconds_arg(duration)))
    out_opts += [("-ac", channels), ("-ar", rate), ("-f", "f32le"), ("-c:a", "pcm_f32le")]
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src), in_opts)],
        outputs=[OutputSpec("pipe:1", out_opts)],
        description=f"pcm {src.name}",
    )


def ebur128_measure(src: Path) -> FFmpegCommand:
    """Integrated loudness and true peak of the first audio stream (summary on stderr).

    Used by tests as an independent reference for MosAic's own BS.1770 meter."""
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src))],
        outputs=[
            OutputSpec(
                "-",
                [
                    ("-map", "0:a:0"),
                    ("-af", chain(Filter.of("ebur128", framelog="quiet", peak="true"))),
                    ("-f", "null"),
                ],
            )
        ],
        description=f"ebur128 {src.name}",
        loglevel="info",
    )


def extract_data_stream(src: Path, stream_index: int) -> FFmpegCommand:
    """Raw packets of a data stream (e.g. GoPro GPMF ``gpmd``) concatenated on stdout."""
    return FFmpegCommand(
        inputs=[InputSpec(media_path(src))],
        outputs=[
            OutputSpec("pipe:1", [("-map", f"0:{stream_index}"), ("-c", "copy"), ("-f", "data")])
        ],
        description=f"data stream {src.name}#{stream_index}",
    )
