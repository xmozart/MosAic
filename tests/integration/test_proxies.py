"""Proxies (M0 step 5): CFR 720p SDR, rotation, tone mapping, range, VFR→CFR, tick map."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import select

from mosaic.devtools import barcode
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run
from mosaic.media.proxy import ProxyInfo, load_proxy, proxy_frame_to_source_ticks
from mosaic.storage.models_project import Asset, AssetFile, MediaFile
from mosaic.storage.projects import Project
from tests.support.media import (
    cell_mean,
    decode_barcodes,
    luma_frame,
    nearest_index,
    source_frame_times,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def analyzed(analyzed_corpus: Project) -> Project:
    return analyzed_corpus


def _assets(project: Project) -> dict[str, tuple[Asset, list[Path]]]:
    out = {}
    with project.db.session() as s:
        for a in s.scalars(select(Asset).where(Asset.kind == "video", Asset.status == "ok")):
            files = [
                project.root / rel
                for rel in s.scalars(
                    select(MediaFile.rel_path)
                    .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
                    .where(AssetFile.asset_id == a.id)
                    .order_by(AssetFile.order)
                )
            ]
            out[files[0].name] = (a, files)
    return out


def _video_cases(corpus: Path) -> int:
    manifest = json.loads((corpus / "manifest.json").read_text())
    return sum(
        1
        for c in manifest["cases"]
        if c["files"] and not c["expect_unsupported"] and not c["expect_deferred"]
    )


def _stream(bins: FFmpegBinaries, px: ProxyInfo) -> dict:  # type: ignore[type-arg]
    info = json.loads(run(bins, builders.ffprobe_json(px.path)).stdout)
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def test_proxy_formats(analyzed: Project, ffmpeg_bin: FFmpegBinaries) -> None:
    for name, (asset, _) in _assets(analyzed).items():
        px = load_proxy(analyzed, asset.id)
        v = _stream(ffmpeg_bin, px)
        assert v["codec_name"] == "h264", name
        assert v["pix_fmt"] == "yuv420p", name
        assert v.get("color_range") == "tv", name
        for tag in ("color_transfer", "color_primaries", "color_space"):
            assert v.get(tag) == "bt709", f"{name}: {tag}={v.get(tag)}"
        assert Fraction(v["r_frame_rate"]) <= 30, name
        assert Fraction(v["avg_frame_rate"]) == Fraction(v["r_frame_rate"]), f"{name} not CFR"
        if name.startswith("rotated"):
            assert (v["width"], v["height"]) == (360, 640), name
            assert not v.get("side_data_list"), "proxy must be upright, not flagged"
        audio = json.loads(run(ffmpeg_bin, builders.ffprobe_json(px.path)).stdout)["streams"]
        has_audio = any(s["codec_type"] == "audio" for s in audio)
        assert has_audio == (asset.audio_stream_index is not None), name


def test_tick_map_names_the_source_frame_each_proxy_frame_shows(
    analyzed: Project, ffmpeg_bin: FFmpegBinaries, corpus_dir: Path
) -> None:
    checked = 0
    kinds = {}
    for name, (asset, files) in _assets(analyzed).items():
        px = load_proxy(analyzed, asset.id)
        kinds[name] = px.tickmap["kind"]
        w, h = (180, 320) if px.height > px.width else (320, 180)
        got = decode_barcodes(ffmpeg_bin, px.path, w, h)
        assert len(got) == px.frames, name
        times = source_frame_times(ffmpeg_bin, files)
        # The barcode is drawn in coded orientation, so a display-rotated proxy shows it
        # turned: 90° CCW display needs 3 quarter-turns to read, 270° needs 1.
        want_turns = {0: 0, 90: 3, 180: 2, 270: 1}[asset.rotation]
        src = decode_barcodes(
            ffmpeg_bin, files[0], *((180, 320) if asset.rotation in (90, 270) else (320, 180))
        )[0]
        assert src is not None
        assert src.rotation == want_turns, f"{name}: FFmpeg autorotate disagrees"
        for i, d in enumerate(got):
            assert d is not None, f"{name}: proxy frame {i} has no readable barcode"
            assert d.rotation == want_turns, f"{name}: proxy frame {i} has wrong orientation"
            # Invariant 4: the tick map names the source frame the proxy frame shows.
            t = proxy_frame_to_source_ticks(px.tickmap, i) * px.tb
            mapped = nearest_index(times, t)
            assert abs(d.index - mapped) <= 1, (
                f"{name}: proxy frame {i} shows {d.index}, tick map says {mapped}"
            )
        checked += 1
    assert checked == _video_cases(corpus_dir)
    assert kinds["vfr.mp4"] == "table"
    assert kinds["A001_basic.mp4"] == "affine"


def test_full_range_source_becomes_limited_range(
    analyzed: Project, ffmpeg_bin: FFmpegBinaries
) -> None:
    assets = _assets(analyzed)
    for name in ("full_range.mp4", "A001_basic.mp4"):
        px = load_proxy(analyzed, assets[name][0].id)
        luma = luma_frame(ffmpeg_bin, px.path, px.width, px.height)
        white = cell_mean(luma, 0, 0)  # sync cell, always white
        black = cell_mean(luma, 0, barcode.COLS - 1)  # sync cell, always black
        # RGB 232/24 in limited-range BT.709 is Y ≈ 215/37; a range mix-up gives 232/24.
        assert 205 <= white <= 222, f"{name}: white Y={white:.1f}"
        assert 30 <= black <= 44, f"{name}: black Y={black:.1f}"


def test_hdr_sources_are_tone_mapped_not_retagged(
    analyzed: Project, ffmpeg_bin: FFmpegBinaries
) -> None:
    assets = _assets(analyzed)
    lumas = {}
    for name in ("hlg.mov", "pq.mov"):
        px = load_proxy(analyzed, assets[name][0].id)
        luma = luma_frame(ffmpeg_bin, px.path, px.width, px.height, 30)
        lumas[name] = (cell_mean(luma, 0, 0), float(luma[px.height * 3 // 4 :, :].mean()))
        assert lumas[name][0] > 120, f"{name}: highlights crushed ({lumas[name][0]:.1f})"
    # Identical pixels encoded with different transfer functions must map differently;
    # a proxy that merely retagged the HDR signal as SDR would show them the same.
    assert abs(lumas["hlg.mov"][1] - lumas["pq.mov"][1]) > 5, lumas
