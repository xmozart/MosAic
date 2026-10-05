"""Camera profiles (M1 step 8, ADR 0024): detection, 360 projection, DJI chapters,
the unsupported catalog, and the 360 forward-view builder."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from mosaic.media.ffmpeg import builders
from mosaic.media.probe import parse_probe
from mosaic.media.profiles import (
    DJIProfile,
    FileRecord,
    dji_number,
    insta_projection,
    profile_for,
)
from mosaic.media.scan import MediaType
from mosaic.media.unsupported import unsupported_by_extension, unsupported_codec


def _video(w: int = 1920, h: int = 1080, **extra: Any) -> dict[str, Any]:
    return {
        "index": extra.pop("index", 0),
        "codec_type": "video",
        "codec_name": "h264",
        "width": w,
        "height": h,
        "r_frame_rate": "30/1",
        "avg_frame_rate": "30/1",
        "time_base": "1/90000",
        "start_pts": 0,
        "duration_ts": 540000,
        "pix_fmt": "yuv420p",
        **extra,
    }


def _probe(streams: list[dict[str, Any]], duration: str = "6.0", **tags: str) -> Any:
    return parse_probe(
        {
            "format": {"format_name": "mov,mp4", "duration": duration, "tags": tags},
            "streams": streams,
        }
    )


def _profile(name: str, probe: Any = None) -> str:
    return profile_for(FileRecord(1, name, MediaType.VIDEO, probe, usable=True)).id


def test_detection_by_tags_and_names() -> None:
    assert _profile("x.mp4", _probe([_video()], make="Insta360")) == "insta360"
    assert _profile("x.mp4", _probe([_video()], make="DJI")) == "dji"
    assert _profile("x.mov", _probe([_video()], make="NIKON CORPORATION")) == "nikon_z"
    assert _profile("VID_20250301_101500_00_001.mp4") == "insta360"
    assert _profile("IMG_20250301_101500_00_001.jpg") == "insta360", "beats the iPhone IMG_ rule"
    assert _profile("IMG_1234.HEIC") == "iphone"
    assert _profile("DJI_0001.MP4") == "dji"
    assert _profile("DJI_20250301120000_0007_D.MP4") == "dji"
    assert _profile("DSC_0001.MOV") == "nikon_z"
    assert _profile("clip.insv") == "insta360"
    assert _profile("GX010201.MP4") == "gopro"
    assert _profile("holiday.mp4") == "generic"
    assert dji_number("DJI_20250301120000_0007_D") == 7
    assert dji_number("DJI_0042") == 42
    assert dji_number("DJIX_0042") is None


def test_insta360_projection() -> None:
    assert insta_projection(_probe([_video(640, 320)]), "a.insv") == "dfisheye"
    assert insta_projection(_probe([_video(320, 320)]), "a.insv") == "fisheye"
    two = _probe([_video(320, 320), _video(320, 320, index=1)])
    assert insta_projection(two, "a.insv") == "fisheye"
    assert insta_projection(_probe([_video()]), "a.insv") is None, "flat single-lens"
    assert insta_projection(_probe([_video(640, 320)]), "a.mp4") is None, "exports are flat"


def _dji_file(i: int, n: int, start: datetime, seconds: int) -> FileRecord:
    probe = _probe(
        [_video(duration_ts=seconds * 90000)],
        duration=str(seconds),
        creation_time=start.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
    )
    return FileRecord(i, f"DJI_{n:04d}.MP4", MediaType.VIDEO, probe, usable=True)


@given(
    lengths=st.lists(st.integers(3, 600), min_size=2, max_size=5),
    gaps=st.lists(st.integers(-1, 1), min_size=4, max_size=4),
    split_at=st.integers(1, 4),
    reverse=st.booleans(),
)
def test_dji_chapters_group_by_continuity(
    lengths: list[int], gaps: list[int], split_at: int, reverse: bool
) -> None:
    """Files that continue within ±2 s form one asset; a longer gap starts a new one; the
    order the files arrive in does not matter."""
    t = datetime(2025, 3, 1, 10, 0, tzinfo=UTC)
    files = []
    split = min(split_at, len(lengths) - 1)
    for i, seconds in enumerate(lengths):
        files.append(_dji_file(i + 1, i + 1, t, seconds))
        jump = gaps[i % len(gaps)] + (300 if i + 1 == split else 0)
        t += timedelta(seconds=seconds + jump)
    groups = DJIProfile().group(list(reversed(files)) if reverse else files)
    sizes = sorted(len(g.files) for g in groups)
    assert sizes == sorted([split, len(lengths) - split])
    for g in groups:
        numbers = [dji_number(f.stem) for f in g.files]
        assert numbers == sorted(numbers), "chapters in order"


def test_dji_mixed_time_zones_never_crash() -> None:
    a = _dji_file(1, 1, datetime(2025, 3, 1, 10, 0, tzinfo=UTC), 6)
    b_probe = _probe([_video()], creation_time="2025-03-01T10:00:06")  # no offset
    b = FileRecord(2, "DJI_0002.MP4", MediaType.VIDEO, b_probe, usable=True)
    assert len(DJIProfile().group([a, b])) == 2


def test_unsupported_catalog() -> None:
    for name, words in (
        ("a.braw", "Blackmagic"),
        ("a.R3D", "RED"),
        ("a.NEV", "N-RAW"),
        ("a.360", "GoPro MAX"),
        ("a.insp", "360° photos"),
    ):
        entry = unsupported_by_extension(name)
        assert entry is not None, name
        assert words in entry.reason
        assert entry.fix
    assert unsupported_by_extension("a.mp4") is None
    assert unsupported_codec("prores_raw") is not None
    assert unsupported_codec(None, "aprn") is not None
    assert unsupported_codec("h264", "avc1") is None


def test_forward_view_has_square_pixels() -> None:
    v = float(builders.FORWARD_VFOV)
    h = builders.FORWARD_HFOV
    ratio = math.tan(math.radians(h / 2)) / math.tan(math.radians(v / 2))
    assert abs(ratio - 16 / 9) < 0.001
    spec = builders.ProxySpec(
        inputs=[Path("a.insv")],
        video_index=0,
        audio_index=None,
        width=1280,
        height=720,
        rate=Fraction(30),
        hdr=None,
        full_range=False,
        encoder="libx264",
        bitrate="3M",
        out=Path("out.mp4"),
        projection="dfisheye",
    )
    argv = " ".join(str(a) for a in builders.proxy(spec).argv("ffmpeg"))
    assert "v360=input=dfisheye:output=flat:ih_fov=200:iv_fov=200:h_fov=100" in argv
    assert "v_fov=6767/100:w=1280:h=720" in argv


def test_mux_video_streams_maps_each_source() -> None:
    cmd = builders.mux_video_streams(
        [Path("a.mp4"), Path("b.mp4")], Path("x.insv"), container="mp4"
    )
    argv = [str(a) for a in cmd.argv("ffmpeg")]
    assert argv.count("-map") == 2
    assert "0:v:0" in argv
    assert "1:v:0" in argv
    assert argv[argv.index("-f") + 1] == "mp4"
