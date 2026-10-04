from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mosaic.devtools import barcode
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run

pytestmark = pytest.mark.integration

W, H = 320, 180


def decode_file(bins: FFmpegBinaries, path: Path) -> list[int | None]:
    raw = run(bins, builders.extract_rgb_frames(path, W, H)).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W, 3)
    out: list[int | None] = []
    for f in frames:
        d = barcode.decode(f)
        out.append(d.index if d else None)
    return out


def test_manifest_covers_m0_cases(corpus_dir: Path) -> None:
    names = {c["name"] for c in json.loads((corpus_dir / "manifest.json").read_text())["cases"]}
    required = {
        "vfr",
        "rotated_90",
        "rotated_270",
        "hlg",
        "pq",
        "start_offset",
        "gopro_chapters",
        "no_audio",
        "multi_audio",
        "hfr_120",
        "corrupt",
        "full_range_8bit",
        "hevc10_5994",
    }
    assert required <= names


def test_every_frame_carries_its_index(corpus_dir: Path, ffmpeg_bin: FFmpegBinaries) -> None:
    manifest = json.loads((corpus_dir / "manifest.json").read_text())
    checked = 0
    for case in manifest["cases"]:
        if case["expect_unsupported"] or case["expect_deferred"] or not case["files"]:
            continue
        offsets = case["barcode_offset"] or [0]
        indices: list[int | None] = []
        for f, off in zip(case["files"], offsets, strict=False):
            got = decode_file(ffmpeg_bin, corpus_dir / f)
            assert got[0] == off, (case["name"], f)
            indices += got
        assert indices == list(range(case["frames"])), case["name"]
        checked += 1
    assert checked >= 12


def _probe(bins: FFmpegBinaries, path: Path) -> dict:
    return json.loads(run(bins, builders.ffprobe_json(path)).stdout)


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []):
        if "rotation" in sd:
            return int(sd["rotation"]) % 360
    return 0


def test_cases_have_the_properties_they_claim(corpus_dir: Path, ffmpeg_bin: FFmpegBinaries) -> None:
    from fractions import Fraction

    manifest = json.loads((corpus_dir / "manifest.json").read_text())
    for case in manifest["cases"]:
        if case["expect_unsupported"] or case["expect_deferred"] or not case["files"]:
            continue
        for f in case["files"] + case["sidecars"]:
            assert (corpus_dir / f).is_file(), f
        info = _probe(ffmpeg_bin, corpus_dir / case["files"][0])
        video = [s for s in info["streams"] if s["codec_type"] == "video"]
        audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
        v = video[0]
        name = case["name"]
        assert len(audio) == case["audio_tracks"], name
        assert Fraction(v["r_frame_rate"]) == Fraction(case["rate"]), name
        # ffprobe reports the display matrix as counter-clockwise degrees.
        assert _rotation(v) in (
            {0} if not case["rotation"] else {case["rotation"], 360 - case["rotation"]}
        ), name
        if case["full_range"]:
            assert v["color_range"] == "pc", name
        if case["hdr"]:
            expected = {"hlg": "arib-std-b67", "pq": "smpte2084"}[case["hdr"]]
            assert v["color_transfer"] == expected, name
            assert v["pix_fmt"].startswith(case["pix_fmt"][:7]) or case["pix_fmt"] == "p010le"
        if name == "start_offset":
            assert Fraction(v["start_time"]) > 1, name
        if name == "hevc10_5994":
            assert v["codec_name"] == "hevc"
            assert "10" in v["pix_fmt"], v["pix_fmt"]
        if case["vfr"]:
            pk = json.loads(
                run(
                    ffmpeg_bin, builders.ffprobe_packets(corpus_dir / case["files"][0], v["index"])
                ).stdout
            )
            durations = {int(p["duration"]) for p in pk["packets"] if "duration" in p}
            assert len(durations) > 1, "VFR clip has uniform packet durations"
