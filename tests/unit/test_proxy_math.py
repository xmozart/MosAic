from __future__ import annotations

from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from mosaic.media.ffmpeg import builders
from mosaic.media.proxy import (
    ChapterInfo,
    ProxyPlan,
    build_tick_map,
    cfr_verified,
    parse_pts_lines,
    proxy_frame_to_source_ticks,
    proxy_frame_to_ticks,
    proxy_rate,
    proxy_size,
    ticks_to_proxy_frame,
)

RATES = st.sampled_from([Fraction(24000, 1001), Fraction(25), Fraction(30000, 1001), Fraction(30)])
TBS = st.sampled_from(
    [
        Fraction(1, 90000),
        Fraction(1, 60000),
        Fraction(1, 600),
        Fraction(1, 15360),
        Fraction(1, 30000),
    ]
)


def test_proxy_rate_caps_at_thirty() -> None:
    assert proxy_rate(Fraction(60000, 1001)) == Fraction(30000, 1001)
    assert proxy_rate(Fraction(120)) == 30
    assert proxy_rate(Fraction(240)) == 30
    assert proxy_rate(Fraction(25)) == 25
    assert proxy_rate(Fraction(50)) == 25
    assert proxy_rate(None) == 30


def test_proxy_size() -> None:
    assert proxy_size(3840, 2160) == (1280, 720)
    assert proxy_size(2160, 3840) == (720, 1280)
    assert proxy_size(640, 360) == (640, 360)  # never upscaled
    w, h = proxy_size(1920, 1080)
    assert (w % 2, h % 2) == (0, 0)


@given(st.integers(min_value=0, max_value=10**7), RATES, TBS)
def test_frame_tick_round_trip(frame: int, rate: Fraction, tb: Fraction) -> None:
    ticks = proxy_frame_to_ticks(frame, rate, tb)
    assert ticks_to_proxy_frame(ticks, rate, tb) in (frame - 1, frame)
    # A tick inside the frame maps back to it.
    mid = proxy_frame_to_ticks(frame, rate, tb) + int(Fraction(1, 2) / rate / tb)
    assert ticks_to_proxy_frame(mid, rate, tb) == frame


def test_proxy_command_shape(tmp_path) -> None:  # type: ignore[no-untyped-def]
    spec = builders.ProxySpec(
        inputs=[tmp_path / "GX010001.MP4", tmp_path / "GX020001.MP4"],
        video_index=0,
        audio_index=1,
        width=1280,
        height=720,
        rate=Fraction(30000, 1001),
        hdr="hlg",
        full_range=False,
        encoder="libopenh264",
        bitrate="3M",
        video_starts=[Fraction(0), Fraction(0)],
        out=tmp_path / "p.mp4",
    )
    argv = builders.proxy(spec).argv(tmp_path / "ffmpeg")
    graph = argv[argv.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0" in graph
    assert "tonemap=tonemap=hable" in graph
    assert "fps=fps=30000/1001:round=near" in graph
    assert "-copyts" in argv


def _plan(vfr: bool, nb_frames: int | None = 300) -> ProxyPlan:
    tb = Fraction(1, 90000)
    return ProxyPlan(
        asset_id=1,
        chapters=[ChapterInfo("a.mp4", "fp", 0, tb, 0, 0, 900000, nb_frames)],
        video_index=0,
        audio_index=None,
        color_hint="sdr",
        color_range="tv",
        width=640,
        height=360,
        source_rate=Fraction(30),
        rate=Fraction(30),
        tb=tb,
        duration_ticks=900000,
        vfr=vfr,
    )


def test_cfr_verification() -> None:
    assert cfr_verified(_plan(False))
    assert not cfr_verified(_plan(True))
    assert not cfr_verified(_plan(False, None))
    assert not cfr_verified(_plan(False, 250))


def test_tick_maps_affine_and_table() -> None:
    affine = build_tick_map(_plan(False), 300, None)
    assert affine["kind"] == "affine"
    assert proxy_frame_to_source_ticks(affine, 10) == 30000
    # Source frames at 0, 4000, 9000, 12000 ticks; proxy frames every 3000 ticks.
    table = build_tick_map(_plan(True), 5, [0, 4000, 9000, 12000])
    assert table["kind"] == "table"
    assert table["ticks"] == [0, 4000, 4000, 9000, 12000]
    assert proxy_frame_to_source_ticks(table, 1) == 4000
    assert proxy_frame_to_source_ticks(table, 99) == 12000  # clamped


def test_parse_pts_lines() -> None:
    assert parse_pts_lines(b"3003\n0,\nN/A\n1001\n") == [0, 1001, 3003]
