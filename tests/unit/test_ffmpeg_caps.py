from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import (
    Capabilities,
    FFmpegLicense,
    FFmpegLicenseError,
    ensure_license_allowed,
    parse_license,
)
from mosaic.media.ffmpeg.command import Chain, Filter, escape_filter_value, graph


def _caps(lic: FFmpegLicense) -> Capabilities:
    return Capabilities(version="x", license=lic, configuration=())


def test_license_parse() -> None:
    assert parse_license(("--enable-libzimg",)) is FFmpegLicense.LGPL
    assert parse_license(("--enable-gpl", "--enable-libx264")) is FFmpegLicense.GPL
    assert parse_license(("--enable-gpl", "--enable-nonfree")) is FFmpegLicense.NONFREE


def test_gpl_refused_unless_allowed() -> None:
    ensure_license_allowed(_caps(FFmpegLicense.LGPL))
    with pytest.raises(FFmpegLicenseError, match="LGPL build"):
        ensure_license_allowed(_caps(FFmpegLicense.GPL))
    ensure_license_allowed(_caps(FFmpegLicense.GPL), allow_gpl_ffmpeg=True)
    with pytest.raises(FFmpegLicenseError):
        ensure_license_allowed(_caps(FFmpegLicense.NONFREE), allow_gpl_ffmpeg=True)


def test_encoder_preference_order() -> None:
    caps = Capabilities(
        version="x",
        license=FFmpegLicense.LGPL,
        configuration=(),
        encoders=frozenset({"libopenh264", "h264_videotoolbox"}),
    )
    assert caps.h264_encoders() == ["h264_videotoolbox", "libopenh264"]


def test_filter_rendering() -> None:
    f = Filter.of("scale", w=1280, h=-2, flags=None)
    assert f.render() == "scale=w=1280:h=-2"
    g = graph([Chain((Filter.of("null"),), inputs=("0:v",), outputs=("v",))])
    assert g == "[0:v]null[v]"
    assert escape_filter_value("a:b,c") == "a\\:b\\,c"


def test_probe_command_argv_has_no_shell_strings() -> None:
    argv = builders.ffprobe_json(Path("/x/a b.mp4")).argv(Path("/bin/ffprobe"))
    assert argv[0] == "/bin/ffprobe"
    assert argv[-1] == "file:/x/a b.mp4"


def test_listing_parser_handles_ffmpeg7_and_ffmpeg8_formats() -> None:
    from mosaic.media.ffmpeg.capabilities import _parse_listing

    v7 = "Filters:\n  T.. = Timeline\n  ------\n ... zscale            V->V       x\n"
    v8 = "Filters:\n  T.. = Timeline\n  ------\n .S zscale            V->V       x\n"
    enc = "Encoders:\n V..... = Video\n ------\n V....D libopenh264          OpenH264\n"
    assert "zscale" in _parse_listing(v7)
    assert "zscale" in _parse_listing(v8)
    assert _parse_listing(enc) == frozenset({"libopenh264"})


def test_output_may_not_overwrite_input(tmp_path: Path) -> None:
    from mosaic.media.ffmpeg.command import UnsafeCommandError

    src = tmp_path / "clip.mp4"
    with pytest.raises(UnsafeCommandError):
        builders.remux(src, src).argv(Path("/bin/ffmpeg"))


def test_paths_are_file_urls(tmp_path: Path) -> None:
    argv = builders.remux(tmp_path / "-weird: name.mov", tmp_path / "o.mp4").argv(Path("ff"))
    assert f"file:{(tmp_path / '-weird: name.mov').resolve()}" in argv
