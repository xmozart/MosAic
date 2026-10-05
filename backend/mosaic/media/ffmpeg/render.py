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

from mosaic.media.ffmpeg.builders import TONEMAP_TO_SDR, seconds_expr
from mosaic.media.ffmpeg.command import (
    FFmpegCommand,
    Filter,
    InputSpec,
    OptionValue,
    OutputSpec,
    chain,
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


def _video_chain(spec: ChunkSpec, src: str) -> str:
    # Conform first (fewer frames to scale and tone-map for high-frame-rate sources).
    fit: list[Filter] = [
        Filter.of("setpts", f"PTS+{seconds_expr(conform_shift(spec.rate, spec.source_rate))}/TB"),
        Filter.of("fps", fps=spec.rate, round="near", start_time=0),
    ]
    if spec.hdr:
        fit += [
            Filter.of(
                "scale",
                w=spec.width,
                h=spec.height,
                force_original_aspect_ratio="decrease",
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
                force_original_aspect_ratio="decrease",
                force_divisible_by=2,
                flags="bicubic",
                in_range="pc" if spec.full_range else "tv",
                out_range="tv",
                out_color_matrix="bt709",
            )
        )
    fit += [
        Filter.of("pad", w=spec.width, h=spec.height, x="(ow-iw)/2", y="(oh-ih)/2", color="black"),
        Filter.of("setsar", "1"),
        # Exactly ``frames``: clone the last frame if the source ends early, then cut.
        Filter.of("tpad", stop_mode="clone", stop=spec.frames),
        Filter.of("trim", end_frame=spec.frames),
        Filter.of("setpts", "PTS-STARTPTS"),
        Filter.of("format", "yuv420p"),
        Filter.of(
            "setparams", color_primaries="bt709", color_trc="bt709", colorspace="bt709", range="tv"
        ),
    ]
    return f"{src}{chain(*fit)}[vout]"


def chunk(spec: ChunkSpec) -> FFmpegCommand:
    if not spec.pieces:
        raise ValueError("a chunk needs at least one source piece")
    inputs = [InputSpec(media_path(p.path), [("-ss", seconds_expr(p.seek))]) for p in spec.pieces]
    chains: list[str] = []
    n = len(spec.pieces)
    for i, p in enumerate(spec.pieces):
        chains.append(
            f"[{i}:{spec.video_index}]"
            + chain(
                Filter.of("trim", start=seconds_expr(p.start), end=seconds_expr(p.end)),
                # Time 0 is the cut point itself, not the first kept frame: keeps the
                # sub-frame phase that nearest-frame conform depends on.
                Filter.of("setpts", f"PTS-{seconds_expr(p.start)}/TB"),
            )
            + f"[v{i}]"
        )
    if n > 1:
        chains.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
        vsrc = "[vcat]"
    else:
        vsrc = "[v0]"
    chains.append(_video_chain(spec, vsrc))

    end_sample = spec.samples
    if spec.audio_enabled and spec.audio_index is not None:
        for i, p in enumerate(spec.pieces):
            chains.append(
                f"[{i}:{spec.audio_index}]"
                + chain(
                    Filter.of("atrim", start=seconds_expr(p.start), end=seconds_expr(p.end)),
                    Filter.of("asetpts", "PTS-STARTPTS"),
                    Filter.of("aresample", str(AUDIO_RATE)),
                    Filter.of("aformat", sample_fmts="fltp", channel_layouts="stereo"),
                )
                + f"[a{i}]"
            )
        if n > 1:
            chains.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acat]")
            asrc = "[acat]"
        else:
            asrc = "[a0]"
        duration = Fraction(spec.samples, AUDIO_RATE)
        afilters = [
            Filter.of("volume", f"{spec.gain_db}dB"),
            Filter.of("apad", whole_len=end_sample),
            Filter.of("atrim", end_sample=end_sample),
        ]
        if spec.fade_in > 0:
            afilters.append(Filter.of("afade", t="in", st=0, d=seconds_expr(spec.fade_in)))
        if spec.fade_out > 0:
            afilters.append(
                Filter.of(
                    "afade",
                    t="out",
                    st=seconds_expr(max(Fraction(0), duration - spec.fade_out)),
                    d=seconds_expr(spec.fade_out),
                )
            )
        chains.append(f"{asrc}{chain(*afilters)}[aout]")
    else:
        chains.append(
            chain(
                Filter.of("anullsrc", r=AUDIO_RATE, cl="stereo"),
                Filter.of("atrim", end_sample=end_sample),
            )
            + "[aout]"
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
) -> FFmpegCommand:
    """Concatenate the chunks: video stream-copied, audio normalized (pass 2, linear) and
    encoded (AAC in MP4; PCM in Matroska for lossless test renders)."""
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
        ("-map", "0:a:0"),
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
    return FFmpegCommand(
        inputs=[InputSpec(media_path(list_file), [("-f", "concat"), ("-safe", 0)])],
        outputs=[OutputSpec(media_path(out), opts)],
        description=f"assemble {out.name}",
    )
