"""User LUTs (M1 step 10b, ADR 0028): .cube validation and where lut3d sits in the
proxy and render filter chains."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg import render as rb
from mosaic.media.lut import LutError, check_cube


def cube(path: Path, size: int = 2, scale: float = 1.0, rows: int | None = None) -> Path:
    lines = ['TITLE "test"', f"LUT_3D_SIZE {size}"]
    n = 0
    for b in range(size):
        for g in range(size):
            for r in range(size):
                if rows is not None and n >= rows:
                    break
                v = [x / (size - 1) * scale for x in (r, g, b)]
                lines.append(" ".join(f"{x:.6f}" for x in v))
                n += 1
    path.write_text("\n".join(lines) + "\n")
    return path


def test_check_cube(tmp_path: Path) -> None:
    assert check_cube(cube(tmp_path / "ok.cube", 3)) == 3
    with pytest.raises(LutError, match="rows"):
        check_cube(cube(tmp_path / "short.cube", 3, rows=10))
    one_d = tmp_path / "x.cube"
    one_d.write_text("LUT_1D_SIZE 2\n0 0 0\n1 1 1\n")
    with pytest.raises(LutError, match="1D"):
        check_cube(one_d)
    with pytest.raises(LutError, match=r"\.cube"):
        check_cube(tmp_path / "x.3dl")
    bad = tmp_path / "bad.cube"
    bad.write_text("LUT_3D_SIZE 2\n" + "a b c\n" * 8)
    with pytest.raises(LutError):
        check_cube(bad)


def test_lut_comes_first_in_proxies_and_after_conform_in_renders(tmp_path: Path) -> None:
    lut = cube(tmp_path / "a:b, c.cube")
    spec = builders.ProxySpec(
        inputs=[Path("a.mp4")],
        video_index=0,
        audio_index=None,
        width=1280,
        height=720,
        rate=Fraction(30),
        hdr=None,
        full_range=False,
        encoder="libx264",
        bitrate="3M",
        out=Path("o.mp4"),
        lut=lut,
    )
    argv = " ".join(str(a) for a in builders.proxy(spec).argv("ffmpeg"))
    graph = argv[argv.index("[v0]") :] if "[v0]" in argv else argv
    assert "lut3d=file=" in argv
    rgb = graph.index("format=gbrp16le")
    assert graph.index("in_range=tv") < rgb < graph.index("lut3d"), "explicit RGB first"
    after = graph[graph.index("lut3d") :]
    assert "in_range" not in after.split("[vout]")[0], "the main scale reads RGB"
    hdr = builders.ProxySpec(**{**spec.__dict__, "hdr": "pq"})
    assert "tonemap" not in " ".join(str(a) for a in builders.proxy(hdr).argv("ffmpeg"))
    chunk = rb.ChunkSpec(
        pieces=[],
        video_index=0,
        audio_index=None,
        audio_enabled=False,
        gain_db=0,
        fade_in=Fraction(0),
        fade_out=Fraction(0),
        width=1920,
        height=1080,
        rate=Fraction(30),
        frames=30,
        samples=48000,
        hdr=None,
        full_range=False,
        encoder="libx264",
        bitrate="8M",
        out=Path("c.mov"),
        lut=lut,
    )
    vchain = rb._video_chain(chunk, "[0:v]")
    assert vchain.index("fps=") < vchain.index("lut3d") < vchain.rindex("scale=")
    hdr_chunk = rb.ChunkSpec(**{**chunk.__dict__, "hdr": "hlg"})
    assert "tonemap" not in rb._video_chain(hdr_chunk, "[0:v]"), "the LUT replaces it"
