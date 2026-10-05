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


def test_audio_pcm_and_loglevel_argv() -> None:
    from fractions import Fraction

    cmd = builders.audio_pcm(
        Path("/x/p.mp4"), 16000, 1, start=Fraction(598), duration=Fraction(604)
    )
    argv = cmd.argv(Path("ff"))
    i = argv.index("-i")
    assert argv.index("-ss") < i  # input-side seek
    assert argv[argv.index("-t") + 1] == "604000000us"
    assert argv.index("-t") > i
    assert argv[argv.index("-map") + 1] == "0:a:0"
    assert argv[argv.index("-f", i) + 1] == "f32le"
    assert argv[argv.index("-loglevel") + 1] == "error"
    measure = builders.ebur128_measure(Path("/x/p.mp4")).argv(Path("ff"))
    assert measure[measure.index("-loglevel") + 1] == "info"


def test_select_frames_stays_under_the_expression_limit() -> None:
    """Real footage hit FFmpeg's expression limit with 120 terms (M0 step 12)."""
    from fractions import Fraction
    from pathlib import Path

    import pytest

    from mosaic.media import visual
    from mosaic.media.ffmpeg.builders import MAX_SELECT_FRAMES, select_frames

    assert visual.BATCH <= MAX_SELECT_FRAMES
    cmd = select_frames(Path("/x.mp4"), list(range(0, 64 * 90, 90)), Fraction(30))
    assert cmd.description.startswith("select 64 frames")
    with pytest.raises(ValueError, match="at most 64"):
        select_frames(Path("/x.mp4"), list(range(0, 65 * 90, 90)), Fraction(30))


def test_audio_sample_count_command() -> None:
    from pathlib import Path

    from mosaic.media.ffmpeg.builders import audio_sample_count

    cmd = audio_sample_count(Path("/x.mp4"))
    argv = cmd.argv(Path("/bin/ffmpeg"))
    joined = " ".join(argv)
    assert "-map 0:a:0" in joined
    assert "astats=measure_perchannel=none:measure_overall=Number_of_samples" in joined
    assert argv[-3:] == ["-f", "null", "-"]
    assert argv[argv.index("-loglevel") + 1] == "info"
