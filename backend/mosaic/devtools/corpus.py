"""Synthetic corpus generator (``mosaic-dev gen-corpus``), EVALUATION.md §1.

Every video frame carries a frame-index barcode (``devtools.barcode``). The generator
writes ``manifest.json`` describing each case so tests can assert on it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image

from mosaic.devtools import barcode
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.builders import ColorTags, LavfiAudio, SynthSpec, VideoEncoding
from mosaic.media.ffmpeg.capabilities import (
    Capabilities,
    FFmpegBinaries,
    ensure_license_allowed,
    probe_capabilities,
)
from mosaic.media.ffmpeg.command import escape_filter_value
from mosaic.media.ffmpeg.run import run, run_streaming_stdin

SPEECH_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "audio"
    / "librispeech-1272-128104-0002.flac"
)
SPEECH_OFFSET_MS = 1000

HEVC10_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "media" / "hevc10_5994.mov"
)

# Mid-tone scene colors: never near the barcode's black/white levels.
_SCENE_COLORS = [
    (70, 110, 150),
    (150, 100, 70),
    (90, 140, 90),
    (140, 90, 140),
    (120, 130, 80),
    (80, 120, 130),
]


@dataclass
class CaseInfo:
    name: str
    files: list[str]
    purpose: str
    rate: str | None = None
    frames: int | None = None
    width: int | None = None
    height: int | None = None
    rotation: int = 0
    vfr: bool = False
    hdr: str | None = None
    pix_fmt: str | None = None
    scene_frames: int | None = None  # a new synthetic scene starts every N source frames
    shake_px: int = 0  # synthetic camera shake amplitude
    transcript: str | None = None
    duplicate_of: str | None = None  # same pictures as this file
    wobble_frames: int | None = None  # camera shake only in the first N frames
    speech_offset_ms: int | None = None
    audio_tracks: int = 0
    full_range: bool = False
    expect_unsupported: bool = False
    expect_deferred: bool = False
    chapters: int = 1
    sidecars: list[str] = field(default_factory=list)
    barcode_offset: list[int] = field(default_factory=list)
    skipped_reason: str | None = None


def render_frame(
    width: int,
    height: int,
    index: int,
    scene_len: int,
    seed: int,
    shake_px: int = 0,
    shake_frames: int | None = None,
) -> np.ndarray:
    """Synthetic picture: per-scene mid-tone background with texture, a moving block,
    and the barcode band on top."""
    scene = index // max(scene_len, 1)
    color = _SCENE_COLORS[(scene + seed) % len(_SCENE_COLORS)]
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:] = color
    # Static per-scene texture so sharpness and embeddings are not degenerate.
    rng = np.random.default_rng(seed * 1000 + scene)
    tex = rng.integers(-18, 18, size=(height // 8 + 1, width // 8 + 1, 1), dtype=np.int16)
    tex = tex.repeat(8, axis=0).repeat(8, axis=1)[:height, :width]
    frame[:] = np.clip(frame.astype(np.int16) + tex, 60, 190).astype(np.uint8)
    # Moving block in the lower part of the frame.
    bh = barcode.band_height(height)
    size = max(8, height // 6)
    span = max(1, width - size)
    x = (index * 4) % (2 * span)
    x = x if x < span else 2 * span - x
    y = bh + (height - bh - size) // 2
    frame[y : y + size, x : x + size] = (170, 160, 100)
    if shake_px and (shake_frames is None or index < shake_frames):
        # Camera shake: the picture below the barcode band jumps a few pixels every frame.
        jitter = np.random.default_rng(10_000 + index).integers(-shake_px, shake_px + 1, 2)
        frame[bh:] = np.roll(frame[bh:], shift=(int(jitter[0]), int(jitter[1])), axis=(0, 1))
    barcode.draw(frame, index)
    return frame


def _write_frames(
    binaries: FFmpegBinaries, spec: SynthSpec, frame_fn: Callable[[int], np.ndarray]
) -> None:
    chunks = (frame_fn(i).tobytes() for i in range(spec.frames))
    run_streaming_stdin(binaries, builders.synth_from_rawvideo(spec), chunks)


def _h264(caps: Capabilities) -> VideoEncoding:
    if caps.has_encoder("libopenh264"):
        return VideoEncoding("libopenh264", "yuv420p", (("-b:v", "3M"), ("-g", 30)))
    if caps.has_encoder("h264_videotoolbox"):
        return VideoEncoding("h264_videotoolbox", "yuv420p", (("-b:v", "3M"), ("-g", 30)))
    raise RuntimeError("no H.264 encoder (libopenh264 or VideoToolbox) in this FFmpeg build")


def _hevc10(caps: Capabilities) -> VideoEncoding | None:
    if caps.has_encoder("hevc_videotoolbox"):
        return VideoEncoding(
            "hevc_videotoolbox",
            "p010le",
            (("-profile:v", "main10"), ("-b:v", "4M"), ("-g", 30)),
            tag="hvc1",
        )
    return None


def _sine(freq: int, layout: str = "stereo", volume: str = "0.5") -> LavfiAudio:
    channels = "aformat=channel_layouts=" + layout
    return LavfiAudio(
        f"sine=frequency={freq}:sample_rate=48000,volume={volume},{channels}", layout=layout
    )


class CorpusGenerator:
    def __init__(self, out_dir: Path, binaries: FFmpegBinaries, scale: int = 1) -> None:
        self.out = out_dir
        self.bin = binaries
        self.caps = probe_capabilities(binaries.ffmpeg)
        ensure_license_allowed(self.caps)
        self.scale = scale
        self.cases: list[CaseInfo] = []
        self._last_scene_len: int | None = None
        self._tmp_dir: Path | None = None

    @property
    def _tmp(self) -> Path:
        if self._tmp_dir is None:
            self._tmp_dir = Path(tempfile.mkdtemp(prefix="mosaic-corpus-"))
        return self._tmp_dir

    def _video(
        self,
        name: str,
        *,
        w: int = 640,
        h: int = 360,
        rate: Fraction = Fraction(30000, 1001),
        seconds: int = 10,
        encoding: VideoEncoding | None = None,
        color: ColorTags | None = None,
        audio: tuple[builders.AudioSource, ...] = (_sine(440),),
        scene_seconds: int = 4,
        seed: int = 0,
        setpts: str | None = None,
        first_index: int = 0,
        out: Path | None = None,
        frames: int | None = None,
        container: str | None = None,
        shake_px: int = 0,
        shake_frames: int | None = None,
        metadata: tuple[tuple[str, str], ...] = (),
        video_metadata: tuple[tuple[str, str], ...] = (),
    ) -> int:
        n = frames if frames is not None else int(seconds * rate)
        scene_len = int(scene_seconds * rate)
        self._last_scene_len = scene_len
        spec = SynthSpec(
            out=out or self.out / name,
            width=w,
            height=h,
            rate=rate,
            frames=n,
            encoding=encoding or _h264(self.caps),
            color=color or ColorTags(),
            audio=audio,
            setpts_expr=setpts,
            fps_mode_passthrough=setpts is not None,
            container=container,
            metadata=metadata,
            video_metadata=video_metadata,
        )
        _write_frames(
            self.bin,
            spec,
            lambda i: render_frame(w, h, first_index + i, scene_len, seed, shake_px, shake_frames),
        )
        return n

    def _add(self, info: CaseInfo) -> None:
        is_video = info.files and not (info.expect_unsupported or info.expect_deferred)
        if is_video and info.scene_frames is None:
            info.scene_frames = self._last_scene_len
        self.cases.append(info)

    def speech(self) -> None:
        if not SPEECH_FIXTURE.is_file():
            self._add(CaseInfo("speech", [], "transcription", skipped_reason="no speech fixture"))
            return
        src = escape_filter_value(str(SPEECH_FIXTURE))
        audio = LavfiAudio(
            f"amovie={src},adelay={SPEECH_OFFSET_MS}:all=1,apad,aresample=48000,"
            "aformat=channel_layouts=stereo"
        )
        n = self._video("speech.mp4", seconds=15, seed=14, scene_seconds=60, audio=(audio,))
        text = SPEECH_FIXTURE.with_suffix(".txt").read_text().strip()
        self._add(
            CaseInfo(
                "speech",
                ["speech.mp4"],
                "VAD, transcription, word ticks",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
                transcript=text,
                speech_offset_ms=SPEECH_OFFSET_MS,
            )
        )

    def duplicate(self) -> None:
        """Same pictures as A002_basic.mp4 (seed 2, 25 fps), different sound."""
        n = self._video(
            "A003_dup.mp4", seconds=20 * self.scale, rate=Fraction(25), seed=2, audio=(_sine(330),)
        )
        self._add(
            CaseInfo(
                "duplicate",
                ["A003_dup.mp4"],
                "similarity grouping",
                rate="25/1",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
                duplicate_of="A002_basic.mp4",
            )
        )

    def wobble(self) -> None:
        """Camera-start wobble: shake in the first 2 s only (usable_range trimming)."""
        rate = Fraction(30000, 1001)
        wobble = int(2 * rate)
        n = self._video(
            "wobble.mp4",
            seconds=10,
            rate=rate,
            seed=15,
            shake_px=12,
            shake_frames=wobble,
            scene_seconds=60,
        )
        self._add(
            CaseInfo(
                "wobble",
                ["wobble.mp4"],
                "usable_range trimming",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
                wobble_frames=wobble,
            )
        )

    def shaky(self) -> None:
        n = self._video("shaky.mp4", seconds=10, seed=13, shake_px=6)
        self._add(
            CaseInfo(
                "shaky",
                ["shaky.mp4"],
                "camera shake metric",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
                shake_px=6,
            )
        )

    def accidental(self) -> None:
        """A 1.2 s recording: the camera was started and stopped by mistake."""
        n = self._video("accidental.mp4", frames=36, seed=15)
        self._add(
            CaseInfo(
                "accidental",
                ["accidental.mp4"],
                "accidental recording rejected by rule",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
            )
        )

    def pocket(self) -> None:
        """Camera recording inside a pocket: dark, flat frames (barcode band kept)."""
        w, h, rate = 640, 360, Fraction(30000, 1001)
        n = int(6 * rate)
        spec = SynthSpec(
            out=self.out / "pocket.mp4",
            width=w,
            height=h,
            rate=rate,
            frames=n,
            encoding=_h264(self.caps),
            color=ColorTags(),
            audio=(_sine(200, volume="0.05"),),
        )

        def frame(i: int) -> np.ndarray:
            img = np.full((h, w, 3), 6, dtype=np.uint8)
            barcode.draw(img, i)
            return img

        _write_frames(self.bin, spec, frame)
        self._last_scene_len = n
        self._add(
            CaseInfo(
                "pocket",
                ["pocket.mp4"],
                "pocket / covered-lens recording rejected by rule",
                rate="30000/1001",
                frames=n,
                width=w,
                height=h,
                audio_tracks=1,
            )
        )

    # ----------------------------------------------------------------- cases

    def basic(self) -> None:
        r = Fraction(30000, 1001)
        n = self._video(
            "A001_basic.mp4", seconds=24 * self.scale, rate=r, seed=0, audio=(_sine(440),)
        )
        self._add(
            CaseInfo(
                "basic_2997",
                ["A001_basic.mp4"],
                "baseline 29.97 material",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
            )
        )
        n = self._video(
            "A002_basic.mp4",
            seconds=20 * self.scale,
            rate=Fraction(25),
            seed=2,
            audio=(_sine(660),),
        )
        self._add(
            CaseInfo(
                "basic_25",
                ["A002_basic.mp4"],
                "baseline 25 fps material",
                rate="25/1",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
            )
        )

    def vfr(self) -> None:
        # Frame k is displayed at k/30 + floor(k/3)/60 s: every third interval is longer.
        n = self._video(
            "vfr.mp4", seconds=12, rate=Fraction(30), seed=1, setpts="(N/30+floor(N/3)/60)/TB"
        )
        self._add(
            CaseInfo(
                "vfr",
                ["vfr.mp4"],
                "timing and PTS mapping",
                rate="30/1",
                frames=n,
                width=640,
                height=360,
                vfr=True,
                audio_tracks=1,
            )
        )

    def rotated(self) -> None:
        for deg in (90, 270):
            tmp = self._tmp / f"rot{deg}.mp4"
            n = self._video(f"rot{deg}.mp4", seconds=8, seed=3, out=tmp)
            run(
                self.bin, builders.remux(tmp, self.out / f"rotated_{deg}.mp4", display_rotation=deg)
            )
            self._add(
                CaseInfo(
                    f"rotated_{deg}",
                    [f"rotated_{deg}.mp4"],
                    "display-matrix rotation",
                    rate="30000/1001",
                    frames=n,
                    width=640,
                    height=360,
                    rotation=deg,
                    audio_tracks=1,
                )
            )

    def hdr(self) -> None:
        enc = _hevc10(self.caps)
        for kind, trc in (("hlg", "arib-std-b67"), ("pq", "smpte2084")):
            tags = ColorTags(primaries="bt2020", trc=trc, matrix="bt2020nc", range="tv")
            name = f"{kind}.mov"
            encoding = enc or _h264(self.caps)
            n = self._video(
                name, seconds=8, seed=4, rate=Fraction(30), color=tags, encoding=encoding
            )
            self._add(
                CaseInfo(
                    kind,
                    [name],
                    f"{kind.upper()} tone mapping",
                    rate="30/1",
                    frames=n,
                    width=640,
                    height=360,
                    hdr=kind,
                    audio_tracks=1,
                    pix_fmt=encoding.pix_fmt,
                )
            )

    def start_offset(self) -> None:
        tmp = self._tmp / "offset_src.mp4"
        n = self._video("offset.mp4", seconds=10, seed=5, out=tmp)
        run(
            self.bin,
            builders.remux(tmp, self.out / "start_offset.mp4", output_ts_offset=Fraction(3, 2)),
        )
        self._add(
            CaseInfo(
                "start_offset",
                ["start_offset.mp4"],
                "nonzero start_time / edit list",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
            )
        )

    def gopro_chapters(self) -> None:
        r = Fraction(30000, 1001)
        n1 = int(8 * r)
        n2 = int(6 * r)
        self._video("GX010042.MP4", frames=n1, rate=r, seed=6, scene_seconds=3)
        self._video("GX020042.MP4", frames=n2, rate=r, seed=6, scene_seconds=3, first_index=n1)
        # Low-resolution camera proxies (sidecars), same timing.
        self._video(
            "GL010042.LRF",
            w=320,
            h=180,
            frames=n1,
            rate=r,
            seed=6,
            scene_seconds=3,
            container="mp4",
        )
        self._video(
            "GL020042.LRF",
            w=320,
            h=180,
            frames=n2,
            rate=r,
            seed=6,
            scene_seconds=3,
            first_index=n1,
            container="mp4",
        )
        self._add(
            CaseInfo(
                "gopro_chapters",
                ["GX010042.MP4", "GX020042.MP4"],
                "chapter grouping and LRF validation",
                rate="30000/1001",
                frames=n1 + n2,
                width=640,
                height=360,
                audio_tracks=1,
                chapters=2,
                sidecars=["GL010042.LRF", "GL020042.LRF"],
                barcode_offset=[0, n1],
            )
        )

    def no_audio(self) -> None:
        n = self._video("no_audio.mp4", seconds=10, seed=7, audio=())
        self._add(
            CaseInfo(
                "no_audio",
                ["no_audio.mp4"],
                "silence generation",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=0,
            )
        )

    def multi_audio(self) -> None:
        n = self._video(
            "multi_audio.mov",
            seconds=10,
            seed=8,
            audio=(_sine(220, "mono", "0.3"), _sine(880, "stereo")),
        )
        self._add(
            CaseInfo(
                "multi_audio",
                ["multi_audio.mov"],
                "audio track selection",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=2,
            )
        )

    def hfr(self) -> None:
        n = self._video("hfr_120.mp4", seconds=6, rate=Fraction(120), seed=9)
        self._add(
            CaseInfo(
                "hfr_120",
                ["hfr_120.mp4"],
                "HFR detection",
                rate="120/1",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
            )
        )

    def full_range(self) -> None:
        tmp = self._tmp / "fr.mp4"
        n = self._video("fr.mp4", seconds=10, seed=10, out=tmp, color=ColorTags(range="pc"))
        run(
            self.bin,
            builders.remux(
                tmp, self.out / "full_range.mp4", video_bsf="h264_metadata=video_full_range_flag=1"
            ),
        )
        self._add(
            CaseInfo(
                "full_range_8bit",
                ["full_range.mp4"],
                "color-range handling",
                rate="30000/1001",
                frames=n,
                width=640,
                height=360,
                audio_tracks=1,
                full_range=True,
            )
        )

    def hevc10_5994(self) -> None:
        name = "hevc10_5994.mov"
        rate = Fraction(60000, 1001)
        n = int(4 * rate)
        enc = _hevc10(self.caps)
        if enc is not None:
            self._video(name, frames=n, rate=rate, seed=11, encoding=enc)
        elif HEVC10_FIXTURE.is_file():
            # No 10-bit HEVC encoder in LGPL Linux builds: use the committed fixture,
            # generated by this same function with VideoToolbox (ADR 0004).
            shutil.copyfile(HEVC10_FIXTURE, self.out / name)
        else:
            self._add(
                CaseInfo(
                    "hevc10_5994",
                    [],
                    "10-bit HEVC 59.94",
                    skipped_reason="no 10-bit HEVC encoder and no fixture",
                )
            )
            return
        self._add(
            CaseInfo(
                "hevc10_5994",
                [name],
                "10-bit HEVC at 59.94",
                rate="60000/1001",
                frames=n,
                scene_frames=int(4 * rate),
                width=640,
                height=360,
                audio_tracks=1,
            )
        )

    def corrupt(self) -> None:
        rng = np.random.default_rng(1234)
        (self.out / "corrupt.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + rng.bytes(64 * 1024))
        self._add(
            CaseInfo(
                "corrupt", ["corrupt.mp4"], "graceful unsupported handling", expect_unsupported=True
            )
        )

    def portrait_photo(self) -> None:
        img = Image.fromarray(render_frame(640, 480, 0, 1, 12))
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation: rotate 90 CW to display
        exif[0x9003] = "2026:07:15 17:32:10"
        img.save(self.out / "IMG_0001.jpg", exif=exif.tobytes(), quality=90)
        self._add(
            CaseInfo(
                "portrait_jpeg",
                ["IMG_0001.jpg"],
                "photo orientation (not a video case)",
                expect_deferred=True,
            )
        )

    # ---------------------------------------------------------------- driver

    # ----------------------------------------------------------------- cameras
    # Synthetic stand-ins for cameras without real fixtures yet (M1 step 8, ADR 0024):
    # file names, tags and stream layouts as those cameras write them. Opt-in
    # (``generate(only={"cameras"})``), so the shared corpus is unchanged.

    def cameras(self) -> None:
        r = Fraction(30000, 1001)
        ins = (("make", "Insta360"), ("model", "Insta360 X3"))
        # Studio export: flat → full.
        self._video("VID_20250301_101500_00_001.mp4", seconds=4, seed=21, metadata=ins)
        self._add(CaseInfo("insta360_flat", ["VID_20250301_101500_00_001.mp4"], "full"))
        # Raw 360, both lenses side by side in one frame → analysis_only (dfisheye).
        self._video(
            "VID_20250301_102000_00_002.insv",
            w=640,
            h=320,
            seconds=4,
            seed=22,
            metadata=ins,
            container="mp4",
        )
        self._add(CaseInfo("insta360_dfisheye", ["VID_20250301_102000_00_002.insv"], "360"))
        # Raw 360, one stream per lens in one file → analysis_only (front lens, fisheye).
        lens = [self._tmp / "lens0.mp4", self._tmp / "lens1.mp4"]
        for i, p in enumerate(lens):
            self._video(p.name, w=320, h=320, seconds=4, seed=23 + i, out=p, audio=())
        run(
            self.bin,
            builders.mux_video_streams(
                lens, self.out / "VID_20250301_103000_00_003.insv", container="mp4"
            ),
        )
        self._add(CaseInfo("insta360_two_stream", ["VID_20250301_103000_00_003.insv"], "360"))
        # Raw 360 as two files (front _00_, back _10_) plus the camera's preview.
        for lens_id, seed in (("00", 25), ("10", 26)):
            self._video(
                f"VID_20250301_104000_{lens_id}_004.insv",
                w=320,
                h=320,
                seconds=4,
                seed=seed,
                metadata=ins,
                container="mp4",
            )
        self._video(
            "LRV_20250301_104000_01_004.lrv",
            w=160,
            h=160,
            seconds=4,
            seed=25,
            container="mp4",
        )
        self._add(
            CaseInfo(
                "insta360_pair",
                ["VID_20250301_104000_00_004.insv", "VID_20250301_104000_10_004.insv"],
                "360 pair",
                sidecars=["LRV_20250301_104000_01_004.lrv"],
            )
        )
        # DJI: two chapters that continue in time, then a separate recording; LRF + SRT.
        dji = (("make", "DJI"), ("model", "Mini 4 Pro"))
        n1 = self._video(
            "DJI_0001.MP4",
            seconds=6,
            rate=r,
            seed=27,
            metadata=(*dji, ("creation_time", "2025-03-01T10:00:00.000000Z")),
        )
        self._video(
            "DJI_0002.MP4",
            seconds=4,
            rate=r,
            seed=27,
            first_index=n1,
            metadata=(*dji, ("creation_time", "2025-03-01T10:00:06.000000Z")),
        )
        self._video(
            "DJI_0003.MP4",
            seconds=4,
            rate=r,
            seed=28,
            metadata=(*dji, ("creation_time", "2025-03-01T10:05:00.000000Z")),
        )
        self._video("DJI_0001.LRF", w=320, h=180, seconds=6, rate=r, seed=27, container="mp4")
        (self.out / "DJI_0001.SRT").write_text(
            "1\n00:00:00,000 --> 00:00:00,033\n[iso : 100] [latitude: 0.0] [longitude: 0.0]\n"
        )
        self._add(
            CaseInfo(
                "dji_chapters",
                ["DJI_0001.MP4", "DJI_0002.MP4", "DJI_0003.MP4"],
                "chapters by numbering and continuous time",
                chapters=2,
                sidecars=["DJI_0001.LRF", "DJI_0001.SRT"],
            )
        )
        # Nikon: a MOV that names its maker, and an N-RAW file (unsupported, with a fix).
        self._video(
            "DSC_0001.MOV",
            seconds=4,
            seed=29,
            metadata=(("make", "NIKON CORPORATION"), ("model", "NIKON Z 6_2")),
        )
        (self.out / "DSC_0002.NEV").write_bytes(b"NEV" + bytes(4096))
        self._add(CaseInfo("nikon", ["DSC_0001.MOV"], "full"))
        self._add(CaseInfo("nikon_nraw", ["DSC_0002.NEV"], "unsupported", expect_unsupported=True))
        # GoPro TimeWarp: GoPro-tagged, silent → flagged timelapse.
        self._video(
            "GX010500.MP4",
            seconds=4,
            seed=30,
            audio=(),
            video_metadata=(("handler_name", "GoPro AVC"),),
        )
        self._add(CaseInfo("gopro_timelapse", ["GX010500.MP4"], "timelapse"))
        # A Blackmagic RAW file: unsupported, with a fix.
        (self.out / "A001_C001.braw").write_bytes(b"BRAW" + bytes(4096))
        self._add(CaseInfo("braw", ["A001_C001.braw"], "unsupported", expect_unsupported=True))

    def generate(self, only: set[str] | None = None) -> list[CaseInfo]:
        self.out.mkdir(parents=True, exist_ok=True)
        steps: dict[str, Callable[[], None]] = {
            "basic": self.basic,
            "vfr": self.vfr,
            "rotated": self.rotated,
            "hdr": self.hdr,
            "start_offset": self.start_offset,
            "gopro_chapters": self.gopro_chapters,
            "no_audio": self.no_audio,
            "multi_audio": self.multi_audio,
            "hfr": self.hfr,
            "full_range": self.full_range,
            "hevc10_5994": self.hevc10_5994,
            "shaky": self.shaky,
            "duplicate": self.duplicate,
            "wobble": self.wobble,
            "accidental": self.accidental,
            "pocket": self.pocket,
            "speech": self.speech,
            "corrupt": self.corrupt,
            "portrait_photo": self.portrait_photo,
        }
        if only and "cameras" in only:
            steps["cameras"] = self.cameras  # opt-in: not part of the shared corpus
        try:
            for key, fn in steps.items():
                if only is None or key in only:
                    fn()
        finally:
            if self._tmp_dir is not None:
                shutil.rmtree(self._tmp_dir, ignore_errors=True)
        manifest = {
            "version": 1,
            "ffmpeg": self.caps.version,
            "cases": [asdict(c) for c in self.cases],
        }
        tmp = self.out / "manifest.json.tmp"
        tmp.write_text(json.dumps(manifest, indent=2))
        os.replace(tmp, self.out / "manifest.json")
        return self.cases
