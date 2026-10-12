"""Render builders (ARCHITECTURE.md §10): event chunks, concatenation, loudness.

A chunk is one timeline event rendered at the timeline format, with exactly ``frames``
video frames and ``samples`` audio samples, so chunks concatenate without drift:

- each source piece (one per chapter file the event touches) is cut by timestamp with
  ``-copyts`` + ``trim``/``atrim`` after a fast input seek a few seconds earlier;
- video is conformed to the timeline rate by nearest frame (``fps``, PTS based, so VFR
  and high-frame-rate sources resample correctly), tone-mapped from HLG/PQ, scaled to fit
  and pillarboxed or letterboxed onto the canvas, and padded or cut to ``frames``;
- audio gets its gain and fades and is padded or cut to ``samples``; a muted event or a
  source without audio gets generated silence (``anullsrc``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal

from mosaic.media.ffmpeg.builders import TONEMAP_TO_SDR, lut_filters, seconds_expr
from mosaic.media.ffmpeg.command import (
    FFmpegCommand,
    Filter,
    InputSpec,
    OptionValue,
    OutputSpec,
    chain,
    escape_filter_value,
    media_path,
)

AUDIO_RATE = 48000
SEEK_MARGIN = Fraction(3)  # seconds of decode before the cut point after an input seek
LOUDNESS_TARGET = "-14"  # LUFS integrated (web)
TRUE_PEAK = "-1.5"  # dBTP target; the acceptance limit is −1 dBTP
LRA = "11"


@dataclass(frozen=True)
class Piece:
    """A cut from one file: ``start``/``end`` are absolute stream seconds (``-copyts``),
    ``seek`` the input seek in seconds from the file start (≤ start)."""

    path: Path
    start: Fraction
    end: Fraction
    seek: Fraction


@dataclass
class ChunkSpec:
    pieces: list[Piece]
    video_index: int
    audio_index: int | None  # None: no usable source audio (silence)
    audio_enabled: bool
    gain_db: int
    fade_in: Fraction  # seconds
    fade_out: Fraction
    width: int
    height: int
    rate: Fraction
    frames: int
    samples: int
    hdr: str | None  # hlg|pq|None
    full_range: bool
    encoder: str  # h264_* or ffv1
    bitrate: str
    out: Path
    source_rate: Fraction | None = None  # for exact nearest-frame conform
    threads: int = 0
    extra: list[tuple[str, OptionValue]] = field(default_factory=list)
    lut: Path | None = None  # final renders of log footage (previews read LUT'd proxies)
    # "fit": scale the whole picture into the frame, bars where shapes differ; "crop": fill
    # the frame and cut the overflow at the centre (ADR 0046).
    framing: Literal["fit", "crop"] = "fit"
    # Where the subject is, in thousandths of the frame (ADR 0076): a crop centres on it,
    # as far as the picture allows; None crops the centre.
    focus: tuple[int, int] | None = None
    # Fades from and to black over this many frames (ADR 0078's dips).
    dip_in: int = 0
    dip_out: int = 0


def crop_origin(focus: tuple[int, int] | None) -> tuple[str, str]:
    """The crop's top-left as expressions: centred on ``focus`` (thousandths of the
    frame), kept inside the picture; the centre without one."""
    if focus is None:
        return "(iw-ow)/2", "(ih-oh)/2"
    fx, fy = focus
    return (
        f"max(0,min(iw-ow,iw*{fx}/1000-ow/2))",
        f"max(0,min(ih-oh,ih*{fy}/1000-oh/2))",
    )


def conform_shift(timeline_rate: Fraction, source_rate: Fraction | None) -> Fraction:
    """Seconds to add to input timestamps so ``fps`` picks the source frame *nearest* each
    output instant: ``fps`` keeps the last input frame that rounds into an output slot,
    so shifting by ½ output frame − ½ source frame makes that frame the nearest one, for
    faster and slower sources alike. Clamped so the first frame stays in slot 0."""
    if not source_rate or source_rate <= 0:
        return Fraction(0)
    shift = Fraction(1, 2) / timeline_rate - Fraction(1, 2) / source_rate
    limit = Fraction(49, 100) / timeline_rate
    return max(-limit, min(limit, shift))


def _dip_filters(frames: int, dip_in: int, dip_out: int) -> list[Filter]:
    """Frame-exact fades from black at the start and to black at the end."""
    out: list[Filter] = []
    if dip_in:
        out.append(Filter.of("fade", t="in", s=0, n=dip_in))
    if dip_out:
        out.append(Filter.of("fade", t="out", s=frames - dip_out, n=dip_out))
    return out


def _video_chain(spec: ChunkSpec, src: str, label: str = "[vout]") -> str:
    # Conform first (fewer frames to scale and tone-map for high-frame-rate sources).
    fit: list[Filter] = [
        Filter.of("setpts", f"PTS+{seconds_expr(conform_shift(spec.rate, spec.source_rate))}/TB"),
        Filter.of("fps", fps=spec.rate, round="near", start_time=0),
    ]
    if spec.lut is not None:  # the LUT replaces tone mapping (ADR 0028)
        fit += lut_filters(spec.lut, spec.full_range)
        fit.append(
            Filter.of(
                "scale",
                w=spec.width,
                h=spec.height,
                force_original_aspect_ratio="increase" if spec.framing == "crop" else "decrease",
                force_divisible_by=2,
                flags="bicubic",
                out_range="tv",
                out_color_matrix="bt709",
            )
        )
    elif spec.hdr:
        fit += [
            Filter.of(
                "scale",
                w=spec.width,
                h=spec.height,
                force_original_aspect_ratio="increase" if spec.framing == "crop" else "decrease",
                force_divisible_by=2,
                flags="bicubic",
            ),
            *TONEMAP_TO_SDR,
        ]
    else:
        fit.append(
            Filter.of(
                "scale",
                w=spec.width,
                h=spec.height,
                force_original_aspect_ratio="increase" if spec.framing == "crop" else "decrease",
                force_divisible_by=2,
                flags="bicubic",
                in_range="pc" if spec.full_range else "tv",
                out_range="tv",
                out_color_matrix="bt709",
            )
        )
    crop_x, crop_y = (escape_filter_value(e) for e in crop_origin(spec.focus))
    fit += [
        Filter.of("crop", w=spec.width, h=spec.height, x=crop_x, y=crop_y)
        if spec.framing == "crop"
        else Filter.of(
            "pad", w=spec.width, h=spec.height, x="(ow-iw)/2", y="(oh-ih)/2", color="black"
        ),
        Filter.of("setsar", "1"),
        # Exactly ``frames``: clone the last frame if the source ends early, then cut.
        Filter.of("tpad", stop_mode="clone", stop=spec.frames),
        Filter.of("trim", end_frame=spec.frames),
        Filter.of("setpts", "PTS-STARTPTS"),
        *_dip_filters(spec.frames, spec.dip_in, spec.dip_out),
        Filter.of("format", "yuv420p"),
        Filter.of(
            "setparams", color_primaries="bt709", color_trc="bt709", colorspace="bt709", range="tv"
        ),
    ]
    return f"{src}{chain(*fit)}{label}"


def chunk(spec: ChunkSpec) -> FFmpegCommand:
    if not spec.pieces:
        raise ValueError("a chunk needs at least one source piece")
    inputs = _inputs(spec.pieces)
    chains = _picture_chains(spec)
    chains += _audio_chains(
        spec.pieces,
        spec.audio_index if spec.audio_enabled else None,
        spec.gain_db,
        spec.fade_in,
        spec.fade_out,
        spec.samples,
    )
    out: list[tuple[str, OptionValue]] = [("-map", "[vout]"), ("-map", "[aout]")]
    out += _video_codec(spec.encoder, spec.bitrate, spec.rate)
    out += [
        ("-c:a", "pcm_s16le"),
        ("-ar", AUDIO_RATE),
        ("-ac", 2),
        # No -frames:v: it would stop muxing before the audio tail is written; the
        # filters already produce exactly ``frames`` frames and ``samples`` samples.
    ]
    if spec.threads:
        out.append(("-threads", spec.threads))
    out += spec.extra
    # MOV with the timeline rate's timescale: exact frame timestamps (Matroska rounds to
    # milliseconds, which makes the stream-copied result variable frame rate).
    out += [("-video_track_timescale", spec.rate.numerator), ("-f", "mov")]
    return FFmpegCommand(
        inputs=inputs,
        outputs=[OutputSpec(media_path(spec.out), out)],
        global_options=[("-copyts", None)],
        filter_complex=";".join(chains),
        description=f"chunk {spec.out.name}",
    )


def _inputs(pieces: list[Piece]) -> list[InputSpec]:
    return [InputSpec(media_path(p.path), [("-ss", seconds_expr(p.seek))]) for p in pieces]


def _picture_chains(
    spec: ChunkSpec, first: int = 0, tag: str = "", label: str = "[vout]"
) -> list[str]:
    """Filter chains ending in ``label``: the pieces' video (inputs from ``first``), cut,
    conformed and fitted to exactly ``spec.frames`` frames."""
    chains: list[str] = []
    n = len(spec.pieces)
    for i, p in enumerate(spec.pieces):
        chains.append(
            f"[{first + i}:{spec.video_index}]"
            + chain(
                Filter.of("trim", start=seconds_expr(p.start), end=seconds_expr(p.end)),
                # Time 0 is the cut point itself, not the first kept frame: keeps the
                # sub-frame phase that nearest-frame conform depends on.
                Filter.of("setpts", f"PTS-{seconds_expr(p.start)}/TB"),
            )
            + f"[v{tag}{i}]"
        )
    if n > 1:
        chains.append(
            "".join(f"[v{tag}{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v{tag}cat]"
        )
        vsrc = f"[v{tag}cat]"
    else:
        vsrc = f"[v{tag}0]"
    chains.append(_video_chain(spec, vsrc, label))
    return chains


def _audio_chains(
    pieces: list[Piece],
    audio_index: int | None,
    gain_db: int,
    fade_in: Fraction,
    fade_out: Fraction,
    samples: int,
    first: int = 0,
    tag: str = "",
    label: str = "[aout]",
) -> list[str]:
    """Filter chains ending in ``label``: the pieces' audio (input ``first + i`` per piece) with
    its gain and fades, exactly ``samples`` long; generated silence without
    ``audio_index``."""
    if audio_index is None or not pieces:
        return [
            chain(
                Filter.of("anullsrc", r=AUDIO_RATE, cl="stereo"),
                Filter.of("atrim", end_sample=samples),
            )
            + label
        ]
    chains: list[str] = []
    n = len(pieces)
    for i, p in enumerate(pieces):
        chains.append(
            f"[{first + i}:{audio_index}]"
            + chain(
                Filter.of("atrim", start=seconds_expr(p.start), end=seconds_expr(p.end)),
                Filter.of("asetpts", "PTS-STARTPTS"),
                Filter.of("aresample", str(AUDIO_RATE)),
                Filter.of("aformat", sample_fmts="fltp", channel_layouts="stereo"),
            )
            + f"[a{tag}{i}]"
        )
    if n > 1:
        chains.append(
            "".join(f"[a{tag}{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a{tag}cat]"
        )
        asrc = f"[a{tag}cat]"
    else:
        asrc = f"[a{tag}0]"
    duration = Fraction(samples, AUDIO_RATE)
    afilters = [
        Filter.of("volume", f"{gain_db}dB"),
        Filter.of("apad", whole_len=samples),
        Filter.of("atrim", end_sample=samples),
    ]
    if fade_in > 0:
        afilters.append(Filter.of("afade", t="in", st=0, d=seconds_expr(fade_in)))
    if fade_out > 0:
        afilters.append(
            Filter.of(
                "afade",
                t="out",
                st=seconds_expr(max(Fraction(0), duration - fade_out)),
                d=seconds_expr(fade_out),
            )
        )
    chains.append(f"{asrc}{chain(*afilters)}{label}")
    return chains


@dataclass
class AudioSpec:
    """An event's own audio window (a J- or L-cut, ADR 0077): ``pieces`` cut from the
    files' ``audio_index`` (None or no pieces: silence), exactly ``samples`` long."""

    pieces: list[Piece]
    audio_index: int | None
    gain_db: int
    fade_in: Fraction  # seconds
    fade_out: Fraction
    samples: int
    out: Path


def audio_chunk(spec: AudioSpec) -> FFmpegCommand:
    """An audio-only chunk (PCM in MOV) that concatenates with the others without drift."""
    inputs = [InputSpec(media_path(p.path), [("-ss", seconds_expr(p.seek))]) for p in spec.pieces]
    chains = _audio_chains(
        spec.pieces if spec.audio_index is not None else [],
        spec.audio_index,
        spec.gain_db,
        spec.fade_in,
        spec.fade_out,
        spec.samples,
    )
    return FFmpegCommand(
        inputs=inputs if spec.audio_index is not None else [],
        outputs=[
            OutputSpec(
                media_path(spec.out),
                [
                    ("-map", "[aout]"),
                    ("-c:a", "pcm_s16le"),
                    ("-ar", AUDIO_RATE),
                    ("-ac", 2),
                    ("-f", "mov"),
                ],
            )
        ],
        global_options=[("-copyts", None)],
        filter_complex=";".join(chains),
        description=f"audio {spec.out.name}",
    )


def _video_codec(encoder: str, bitrate: str, rate: Fraction) -> list[tuple[str, OptionValue]]:
    tags: list[tuple[str, OptionValue]] = [
        ("-color_primaries", "bt709"),
        ("-color_trc", "bt709"),
        ("-colorspace", "bt709"),
        ("-color_range", "tv"),
    ]
    if encoder == "ffv1":
        return [("-c:v", "ffv1"), ("-level", 3), ("-g", 1), *tags]
    gop = max(1, round(rate * 2))
    return [("-c:v", encoder), ("-b:v", bitrate), ("-g", gop), ("-bf", 0), *tags]


def concat_list(paths: list[Path]) -> str:
    """A concat-demuxer list (``file '…'`` lines; a quote is written as ``'\\''``)."""
    lines = []
    for p in paths:
        text = str(p.resolve())
        if "\n" in text or "\r" in text:
            raise ValueError(f"unsupported character in path: {text!r}")
        quoted = text.replace("'", "'\\''")
        lines.append(f"file '{quoted}'\n")
    return "".join(lines)


def loudnorm_measure(list_file: Path) -> FFmpegCommand:
    """Pass 1 of two-pass loudnorm over the concatenated chunks (JSON on stderr)."""
    return FFmpegCommand(
        inputs=[InputSpec(media_path(list_file), [("-f", "concat"), ("-safe", 0)])],
        outputs=[
            OutputSpec(
                "-",
                [
                    ("-map", "0:a:0"),
                    (
                        "-af",
                        chain(
                            Filter.of(
                                "loudnorm",
                                I=LOUDNESS_TARGET,
                                TP=TRUE_PEAK,
                                LRA=LRA,
                                print_format="json",
                            )
                        ),
                    ),
                    ("-f", "null"),
                ],
            )
        ],
        description=f"loudnorm measure {list_file.name}",
        loglevel="info",
    )


@dataclass(frozen=True)
class Loudness:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float


def assemble(
    list_file: Path,
    out: Path,
    measured: Loudness | None,
    container: str,
    total_samples: int,
    rate: Fraction,
    audio_list: Path | None = None,
) -> FFmpegCommand:
    """Concatenate the chunks: video stream-copied, audio normalized (pass 2, linear) and
    encoded (AAC in MP4; PCM in Matroska for lossless test renders). With ``audio_list``
    (a version with J- or L-cuts, ADR 0077) the audio is that list's audio chunks."""
    afilters: list[Filter] = []
    if measured is not None:
        afilters.append(
            Filter.of(
                "loudnorm",
                I=LOUDNESS_TARGET,
                TP=TRUE_PEAK,
                LRA=LRA,
                measured_I=f"{measured.input_i:.2f}",
                measured_TP=f"{measured.input_tp:.2f}",
                measured_LRA=f"{measured.input_lra:.2f}",
                measured_thresh=f"{measured.input_thresh:.2f}",
                offset=f"{measured.target_offset:.2f}",
                linear="true",
            )
        )
    afilters += [
        Filter.of("aresample", str(AUDIO_RATE)),
        # The edit's exact length (each chunk was rounded to whole samples on its own).
        Filter.of("apad", whole_len=total_samples),
        Filter.of("atrim", end_sample=total_samples),
        Filter.of(
            "aformat", sample_fmts="fltp" if container == "mp4" else "s16", channel_layouts="stereo"
        ),
    ]
    opts: list[tuple[str, OptionValue]] = [
        ("-map", "0:v:0"),
        ("-map", "1:a:0" if audio_list is not None else "0:a:0"),
        ("-c:v", "copy"),
        # Re-time the copied frames on the exact grid (no B-frames, so PTS = DTS): the
        # result is constant frame rate however the chunk boundaries were rounded.
        ("-bsf:v", f"setts=ts=N*{rate.denominator}"),
        ("-video_track_timescale", rate.numerator),
        ("-af", chain(*afilters)),
    ]
    if container == "mp4":
        opts += [("-c:a", "aac"), ("-b:a", "192k"), ("-movflags", "+faststart"), ("-f", "mp4")]
    else:
        opts += [("-c:a", "pcm_s16le"), ("-f", "mov")]
    inputs = [InputSpec(media_path(list_file), [("-f", "concat"), ("-safe", 0)])]
    if audio_list is not None:
        inputs.append(InputSpec(media_path(audio_list), [("-f", "concat"), ("-safe", 0)]))
    return FFmpegCommand(
        inputs=inputs,
        outputs=[OutputSpec(media_path(out), opts)],
        description=f"assemble {out.name}",
    )


@dataclass
class StillSpec:
    """A still event: ``canvas`` (an image of the output's shape, made by
    ``media.stills``) panned and zoomed over ``frames`` frames, with silence."""

    canvas: Path
    zoom: str  # zoompan expressions over the output frame number ``on``
    x: str
    y: str
    width: int
    height: int
    rate: Fraction
    frames: int
    samples: int
    encoder: str
    bitrate: str
    out: Path
    threads: int = 0
    dip_in: int = 0  # fades from and to black (ADR 0078)
    dip_out: int = 0


def still_chunk(spec: StillSpec) -> FFmpegCommand:
    """One still event (ADR 0075): the canvas looped, ``zoompan`` at the timeline rate to
    exactly ``frames`` frames at the output size, and generated silence."""
    video = chain(
        Filter.of(
            "zoompan",
            z=escape_filter_value(spec.zoom),
            x=escape_filter_value(spec.x),
            y=escape_filter_value(spec.y),
            d=1,
            s=f"{spec.width}x{spec.height}",
            fps=spec.rate,
        ),
        Filter.of("trim", end_frame=spec.frames),
        Filter.of("setpts", "N/FRAME_RATE/TB"),
        *_dip_filters(spec.frames, spec.dip_in, spec.dip_out),
        Filter.of("scale", in_range="pc", out_range="tv", out_color_matrix="bt709"),
        Filter.of("setsar", "1"),
        Filter.of("format", "yuv420p"),
        Filter.of(
            "setparams", color_primaries="bt709", color_trc="bt709", colorspace="bt709", range="tv"
        ),
    )
    audio = chain(
        Filter.of("anullsrc", r=AUDIO_RATE, cl="stereo"),
        Filter.of("atrim", end_sample=spec.samples),
    )
    out: list[tuple[str, OptionValue]] = [("-map", "[vout]"), ("-map", "[aout]")]
    out += _video_codec(spec.encoder, spec.bitrate, spec.rate)
    out += [("-c:a", "pcm_s16le"), ("-ar", AUDIO_RATE), ("-ac", 2)]
    if spec.threads:
        out.append(("-threads", spec.threads))
    out += [("-video_track_timescale", spec.rate.numerator), ("-f", "mov")]
    return FFmpegCommand(
        inputs=[InputSpec(media_path(spec.canvas), [("-loop", 1), ("-framerate", spec.rate)])],
        outputs=[OutputSpec(media_path(spec.out), out)],
        filter_complex=f"[0:v]{video}[vout];{audio}[aout]",
        description=f"still {spec.out.name}",
    )


def dissolve_chunk(a: ChunkSpec, b: ChunkSpec, out: Path) -> FFmpegCommand:
    """A dissolve (ADR 0078): ``a`` (the outgoing picture past its cut) blended into ``b``
    (the incoming picture before its cut) over all their frames with ``xfade``, and their
    sounds mixed (each spec carries its own fade), exactly ``a.frames`` frames."""
    if a.frames != b.frames or a.samples != b.samples:
        raise ValueError("both sides of a dissolve are the same length")
    if not a.pieces or not b.pieces:
        raise ValueError("a dissolve needs source pieces on both sides")
    first_b = len(a.pieces)
    chains = [
        *_picture_chains(a, 0, "a", "[va]"),
        *_picture_chains(b, first_b, "b", "[vb]"),
        "[va][vb]"
        + chain(
            Filter.of(
                "xfade",
                transition="fade",
                duration=seconds_expr(Fraction(a.frames) / a.rate),
                offset=0,
            ),
            Filter.of("trim", end_frame=a.frames),
            Filter.of("setpts", "PTS-STARTPTS"),
        )
        + "[vout]",
        *_audio_chains(
            a.pieces,
            a.audio_index if a.audio_enabled else None,
            a.gain_db,
            a.fade_in,
            a.fade_out,
            a.samples,
            0,
            "a",
            "[aa]",
        ),
        *_audio_chains(
            b.pieces,
            b.audio_index if b.audio_enabled else None,
            b.gain_db,
            b.fade_in,
            b.fade_out,
            b.samples,
            first_b,
            "b",
            "[ab]",
        ),
        "[aa][ab]"
        + chain(
            Filter.of("amix", inputs=2, normalize=0, duration="first"),
            Filter.of("atrim", end_sample=a.samples),
        )
        + "[aout]",
    ]
    opts: list[tuple[str, OptionValue]] = [("-map", "[vout]"), ("-map", "[aout]")]
    opts += _video_codec(a.encoder, a.bitrate, a.rate)
    opts += [("-c:a", "pcm_s16le"), ("-ar", AUDIO_RATE), ("-ac", 2)]
    if a.threads:
        opts.append(("-threads", a.threads))
    opts += [("-video_track_timescale", a.rate.numerator), ("-f", "mov")]
    return FFmpegCommand(
        inputs=_inputs(a.pieces) + _inputs(b.pieces),
        outputs=[OutputSpec(media_path(out), opts)],
        global_options=[("-copyts", None)],
        filter_complex=";".join(chains),
        description=f"dissolve {out.name}",
    )
