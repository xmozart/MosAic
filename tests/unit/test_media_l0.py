from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path

import pytest

from mosaic.media.inventory import link_sidecars
from mosaic.media.probe import ProbeError, durations_vary, parse_probe, parse_stream
from mosaic.media.profiles import (
    FileRecord,
    GenericProfile,
    GoProProfile,
    IPhoneProfile,
    gopro_chapter,
    lrf_matches,
    normalize_iso,
    profile_for,
    select_audio,
)
from mosaic.media.scan import MediaType, fingerprint, media_type_for, scan


def _video(width: int = 1920, rate: str = "30000/1001", **extra: object) -> dict:
    return {
        "index": 0,
        "codec_type": "video",
        "codec_name": "hevc",
        "width": width,
        "height": 1080,
        "r_frame_rate": rate,
        "avg_frame_rate": rate,
        "time_base": "1/90000",
        "start_pts": 0,
        "duration_ts": 900000,
        "pix_fmt": "yuv420p10le",
        **extra,
    }


def _probe(streams: list[dict], duration: str = "10.0", tags: dict | None = None):  # type: ignore[no-untyped-def]
    return parse_probe(
        {
            "format": {"format_name": "mov,mp4", "duration": duration, "tags": tags or {}},
            "streams": streams,
        }
    )


def _rec(i: int, name: str, probe=None, kind=MediaType.VIDEO) -> FileRecord:  # type: ignore[no-untyped-def]
    return FileRecord(i, name, kind, probe, usable=probe is not None)


def test_parse_stream_is_exact() -> None:
    s = parse_stream(_video(side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}]))
    assert s.time_base == Fraction(1, 90000)
    assert s.rate == Fraction(30000, 1001)
    assert s.rotation == 270
    assert s.bit_depth == 10
    p = _probe([_video()], duration="828.36")
    assert p.duration == Fraction(82836, 100)


def test_durations_vary_ignores_ntsc_rounding() -> None:
    assert not durations_vary([1501, 1502, 1501, 1502])
    assert not durations_vary([20, 20, 20])
    assert durations_vary([3000, 3000, 4500] * 10)
    assert durations_vary([19, 20, 21, 20] * 10)


def test_gopro_chapter_names() -> None:
    assert gopro_chapter("GX010201") == ("GX0201", 1)
    assert gopro_chapter("GX020201") == ("GX0201", 2)
    assert gopro_chapter("GL020201") == ("GL0201", 2)
    assert gopro_chapter("GOPR0042") == ("GOPR0042", 0)
    assert gopro_chapter("GP010042") == ("GOPR0042", 1)
    assert gopro_chapter("IMG_0001") is None


def test_gopro_groups_chapters_and_splits_on_settings_change() -> None:
    p = _probe([_video()])
    other = _probe([_video(width=3840)])
    files = [
        _rec(1, "GX010007.MP4", p),
        _rec(2, "GX020007.MP4", p),
        _rec(3, "GX030007.MP4", other),
        _rec(4, "GX010008.MP4", p),
    ]
    groups = GoProProfile().group(files)
    members = sorted(tuple(f.id for f in g.files) for g in groups)
    assert members == [(1, 2), (3,), (4,)]


def test_gopro_lrf_owner_mapping() -> None:
    p = _probe([_video()])
    owners = [_rec(1, "GX010007.MP4", p), _rec(2, "GX020007.MP4", p)]
    lrfs = [
        _rec(3, "GL020007.LRF", p, MediaType.SIDECAR),
        _rec(4, "GL010099.LRF", p, MediaType.SIDECAR),
    ]
    links = GoProProfile().sidecars(lrfs, owners)
    assert links[0].owner is not None
    assert links[0].owner.id == 2
    assert links[1].owner is None


def test_lrf_validation() -> None:
    a = _probe([_video()], duration="10.0")
    assert lrf_matches(a, _probe([_video(width=640)], duration="10.03")) is None
    assert "frame rate" in (lrf_matches(a, _probe([_video(rate="25/1")])) or "")
    assert "duration" in (lrf_matches(a, _probe([_video(duration_ts=1080000)])) or "")
    # Container durations may differ (audio tails); the video streams decide.
    assert lrf_matches(a, _probe([_video()], duration="10.3")) is None


CID = "com.apple.quicktime.content.identifier"


def test_iphone_detection_capture_time_and_live_photo() -> None:
    tags = {
        "com.apple.quicktime.make": "Apple",
        "com.apple.quicktime.creationdate": "2025-02-21T10:12:10+0400",
        "com.apple.quicktime.content.identifier": "ABC",
    }
    mov = _rec(1, "IMG_0001.MOV", _probe([_video()], duration="2.5", tags=tags))
    photo = _probe([_video()], duration="0", tags={"make": "Apple"})
    still = _rec(2, "IMG_0001.HEIC", photo, MediaType.PHOTO)
    assert profile_for(mov).id == "iphone"
    assert profile_for(still).id == "iphone"
    assert IPhoneProfile().capture_time(mov.probe) == "2025-02-21T10:12:10+04:00"  # type: ignore[arg-type]
    groups = IPhoneProfile().group([mov, still])
    assert [(g.kind, g.status) for g in groups] == [("live_photo", "ok")]
    assert [f.id for f in groups[0].files] == [2, 1], "the still first, then its motion"
    long_mov = _rec(1, "IMG_0001.MOV", _probe([_video()], duration="10", tags=tags))
    assert {g.kind for g in IPhoneProfile().group([long_mov, still])} == {"video", "photo"}
    # Paired by the content identifier both halves carry, whatever their names.
    tagged = _probe([_video()], duration="0", tags={"make": "Apple", **{CID: "ABC"}})
    renamed = _rec(3, "edited_copy.HEIC", tagged, MediaType.PHOTO)
    groups = IPhoneProfile().group([mov, still, renamed])
    live = [g for g in groups if g.kind == "live_photo"]
    assert [[f.id for f in g.files] for g in live] == [[3, 1]]
    # A still whose identifier differs is not paired by name.
    other = _probe([_video()], duration="0", tags={"make": "Apple", **{CID: "XYZ"}})
    named = _rec(4, "IMG_0001.HEIC", other, MediaType.PHOTO)
    assert {g.kind for g in IPhoneProfile().group([mov, named])} == {"video", "photo"}


def test_select_audio_prefers_stereo_aac() -> None:
    p = _probe(
        [
            _video(),
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 1,
                "time_base": "1/48000",
            },
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "time_base": "1/48000",
            },
        ]
    )
    chosen = select_audio(p)
    assert chosen is not None
    assert chosen.index == 2


def test_normalize_iso() -> None:
    assert normalize_iso("2025-02-21T06:50:12.000000Z") == "2025-02-21T06:50:12+00:00"
    assert normalize_iso("garbage") is None
    frac = normalize_iso("2025-02-21T06:50:12.250400Z")
    assert frac == "2025-02-21T06:50:12.250+00:00"
    assert normalize_iso(frac) == frac, "idempotent"
    assert normalize_iso("2025-02-21T06:50:12.000400Z") == "2025-02-21T06:50:12+00:00"


def test_scan_skips_workspace_hidden_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "MosAic").mkdir()
    (tmp_path / "MosAic" / "x.mp4").write_bytes(b"1")
    (tmp_path / ".hidden.mp4").write_bytes(b"1")
    (tmp_path / ".DS_Store").write_bytes(b"1")
    (tmp_path / ".mosaic-project.json").write_text("{}")
    (tmp_path / "day1").mkdir()
    (tmp_path / "day1" / "b.MP4").write_bytes(b"22")
    (tmp_path / "a.jpg").write_bytes(b"333")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.mp4"
    outside.write_bytes(b"x")
    os.symlink(outside, tmp_path / "link.mp4")
    found = [(f.rel_path, f.media_type) for f in scan(tmp_path)]
    assert found == [("a.jpg", MediaType.PHOTO), ("day1/b.MP4", MediaType.VIDEO)]


def test_media_types_and_fingerprint(tmp_path: Path) -> None:
    assert media_type_for(Path("x.LRF")) is MediaType.SIDECAR
    assert media_type_for(Path("x.nef")) is MediaType.PHOTO
    assert media_type_for(Path("x.txt")) is MediaType.OTHER
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(300_000))
    a = fingerprint(f, f.stat().st_size)
    assert a == fingerprint(f, f.stat().st_size)
    assert a.startswith("300000-")


def test_bit_depth_semi_planar_and_missing_time_base() -> None:
    assert parse_stream(_video(pix_fmt="p010le")).bit_depth == 10
    assert parse_stream(_video(pix_fmt="yuv420p")).bit_depth == 8
    with pytest.raises(ProbeError, match="time base"):
        parse_stream({"index": 0, "codec_type": "video"})


def test_durations_vary_ignores_outlier_first_and_last_packets() -> None:
    assert not durations_vary([5000] + [1501, 1502] * 200 + [1])


def test_mixed_folder_links_each_sidecar_to_its_own_owner() -> None:
    p = _probe([_video()])
    owners = [_rec(1, "GX010007.MP4", p), _rec(2, "DJI_0001.MP4", p)]
    lrfs = [
        _rec(3, "GL010007.LRF", p, MediaType.SIDECAR),
        _rec(4, "DJI_0001.LRF", p, MediaType.SIDECAR),
        _rec(5, "DJI_0002.SRT", None, MediaType.SIDECAR),
    ]
    links = {link.sidecar.id: link for link in link_sidecars(lrfs, owners)}
    assert links[3].owner is not None
    assert links[3].owner.id == 1
    assert links[4].owner is not None
    assert links[4].owner.id == 2
    assert links[4].proxy_candidate
    assert links[5].owner is None


def test_capability_names_unsupported_formats() -> None:
    cap = GenericProfile().capability(None, "trip/clip.360")
    assert cap.level == "unsupported"
    assert cap.fix
    assert GenericProfile().capability(None, "x/clip.nev").reason
    assert GenericProfile().capability(_probe([_video()]), "a.mp4").level == "full"
    assert GenericProfile().capability(_probe([]), "a.mp4").level == "unsupported"


def test_gopro_make_only_when_the_file_says_so() -> None:
    plain = _probe([_video()])
    confirmed = _probe([_video(tags={"handler_name": "\x0bGoPro H.265"})])
    assert GoProProfile().camera(plain) == (None, None)
    assert GoProProfile().camera(confirmed) == ("GoPro", None)
    assert GoProProfile().detect(plain, "GX010001.MP4") == pytest.approx(0.6)
    assert GoProProfile().detect(confirmed, "clip.mp4") == pytest.approx(0.95)


def test_subprocess_timeouts_degrade_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from mosaic.media import probe as probing
    from mosaic.media.ffmpeg.capabilities import FFmpegBinaries

    def hang(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=1)

    monkeypatch.setattr(probing, "run", hang)
    b = FFmpegBinaries(Path("ffmpeg"), Path("ffprobe"))
    with pytest.raises(ProbeError, match="timed out"):
        probing.ffprobe(b, Path("x.mp4"))
    assert probing.decode_check(b, Path("x.mp4")) == "decoding timed out"
    assert probing.video_vfr_from_packets(b, Path("x.mp4"), 0) is True


def test_bad_probe_output_is_a_probe_error(monkeypatch: pytest.MonkeyPatch) -> None:

    from mosaic.media import probe as probing
    from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
    from mosaic.media.ffmpeg.run import RunResult

    monkeypatch.setattr(probing, "run", lambda *_a, **_k: RunResult([], 0, b"{not json", "", 1))
    with pytest.raises(ProbeError, match="unreadable"):
        probing.ffprobe(FFmpegBinaries(Path("ffmpeg"), Path("ffprobe")), Path("x.mp4"))
