"""Render units (M0 step 11): chapter mapping, sample counts, keys, parsers, commands."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from mosaic.media.ffmpeg.render import ChunkSpec, Piece, assemble, chunk, concat_list
from mosaic.render.plan import SourceFile, chunk_key, pieces, profile, samples_for
from mosaic.render.tasks import parse_ebur128, parse_loudnorm

TB = Fraction(1, 90000)


def _files() -> list[SourceFile]:
    # Two chapters: 0–10 s and 10–20 s of logical time; the second file's video starts at 0.5 s.
    return [
        SourceFile(Path("/a/GX01.MP4"), 0, 900000, Fraction(0), "f1"),
        SourceFile(Path("/a/GX02.MP4"), 900000, 900000, Fraction(1, 2), "f2"),
    ]


def test_pieces_map_logical_time_onto_chapter_files() -> None:
    one = pieces(90000, 270000, TB, _files())
    assert len(one) == 1
    assert (one[0].start, one[0].end) == (Fraction(1), Fraction(3))
    assert one[0].seek == 0
    span = pieces(810000, 1080000, TB, _files())  # 9 s → 12 s crosses the chapter cut
    assert [p.path.name for p in span] == ["GX01.MP4", "GX02.MP4"]
    assert (span[0].start, span[0].end) == (Fraction(9), Fraction(10))
    assert (span[1].start, span[1].end) == (Fraction(1, 2), Fraction(5, 2))
    assert span[0].seek == 6


@given(st.integers(0, 1_799_999), st.integers(1, 900_000))
def test_pieces_cover_the_range_exactly(a: int, length: int) -> None:
    b = min(a + length, 1_800_000)
    ps = pieces(a, b, TB, _files())
    covered = sum((p.end - p.start for p in ps), Fraction(0))
    assert covered == Fraction(b - a) * TB
    for p in ps:
        assert 0 <= p.seek <= p.start


def test_samples_and_profiles() -> None:
    assert samples_for(30, Fraction(30)) == 48000
    assert samples_for(1, Fraction(30000, 1001)) == 1602  # 1601.6 rounded
    assert profile("preview", ["h264_videotoolbox"]).width == 1280
    final = profile("final", ["h264_videotoolbox"])
    assert (final.width, final.height, final.encoder) == (1920, 1080, "h264_videotoolbox")
    assert profile("final", [], lossless=True).encoder == "ffv1"


def test_chunk_key_ignores_timeline_position_but_not_the_profile() -> None:
    event = {
        "asset_id": "ast_0001",
        "source_in": {"ticks": 0, "tb": "1/90000"},
        "source_out": {"ticks": 90000, "tb": "1/90000"},
        "timeline_in": {"frames": 0, "rate": "30"},
        "timeline_out": {"frames": 30, "rate": "30"},
        "audio": {"source_enabled": True, "gain_db": 0},
    }
    moved = event | {
        "timeline_in": {"frames": 300, "rate": "30"},
        "timeline_out": {"frames": 330, "rate": "30"},
    }
    prev = profile("preview", ["h264_videotoolbox"])
    assert chunk_key("p", event, ["f"], prev, "30") == chunk_key("p", moved, ["f"], prev, "30")
    assert chunk_key("p", event, ["f"], prev, "30") != chunk_key(
        "p", event, ["f"], profile("final", ["h264_videotoolbox"]), "30"
    )
    louder = event | {"audio": {"source_enabled": True, "gain_db": -6}}
    assert chunk_key("p", event, ["f"], prev, "30") != chunk_key("p", louder, ["f"], prev, "30")


def test_parsers() -> None:
    stderr = """[Parsed_loudnorm_0 @ 0x1]
{
	"input_i" : "-23.41",
	"input_tp" : "-4.20",
	"input_lra" : "6.10",
	"input_thresh" : "-33.80",
	"output_i" : "-14.02",
	"target_offset" : "0.02"
}"""
    m = parse_loudnorm(stderr)
    assert m is not None
    assert (m.input_i, m.input_tp, m.target_offset) == (-23.41, -4.2, 0.02)
    silent = stderr.replace('"-23.41"', '"-inf"')
    assert parse_loudnorm(silent) is None
    assert parse_loudnorm("nothing") is None
    summary = (
        "Integrated loudness:\n    I:         -14.1 LUFS\n ...\n"
        "  True peak:\n    Peak:       -1.6 dBFS"
    )
    assert parse_ebur128(summary) == (-14.1, -1.6)


def test_chunk_command_shape(tmp_path: Path) -> None:
    spec = ChunkSpec(
        pieces=[Piece(tmp_path / "a.mp4", Fraction(1), Fraction(3), Fraction(0))],
        video_index=0,
        audio_index=None,
        audio_enabled=True,
        gain_db=0,
        fade_in=Fraction(0),
        fade_out=Fraction(0),
        width=1920,
        height=1080,
        rate=Fraction(30000, 1001),
        frames=60,
        samples=96096,
        hdr=None,
        full_range=False,
        encoder="h264_videotoolbox",
        bitrate="14M",
        out=tmp_path / "c.mkv",
    )
    cmd = chunk(spec)
    fc = cmd.filter_complex or ""
    assert "trim=start=1.000000:end=3.000000" in fc
    assert "setpts=PTS-1.000000/TB" in fc  # phase kept relative to the cut point
    assert "fps=fps=30000/1001:round=near" in fc
    assert "trim=end_frame=60" in fc
    assert "anullsrc" in fc  # no source audio: generated silence
    assert "pad=w=1920:h=1080" in fc
    argv = cmd.argv(Path("/bin/ffmpeg"))
    assert "-copyts" in argv
    assert "-frames:v" not in argv  # would cut the audio tail
    lst = concat_list([tmp_path / "it's.mkv"])
    assert lst.startswith("file '")
    assert "'\\''" in lst
    out = assemble(tmp_path / "l.txt", tmp_path / "o.mp4", None, "mp4", 1000, Fraction(30000, 1001))
    joined = " ".join(out.argv(Path("/bin/ffmpeg")))
    assert "atrim=end_sample=1000" in joined
    assert "setts=ts=N*1001" in joined  # constant frame rate on the timeline grid
    assert "-video_track_timescale 30000" in joined
    assert "-f mov" in " ".join(argv)  # exact chunk timestamps (not Matroska ms)


def test_conform_shift_and_end_fallback() -> None:
    from mosaic.media.ffmpeg.render import conform_shift

    r = Fraction(30000, 1001)
    assert conform_shift(r, None) == 0
    assert conform_shift(r, r) == 0
    # 120 fps into 29.97: half an output frame minus half a source frame.
    assert conform_shift(r, Fraction(120)) == Fraction(1, 2) / r - Fraction(1, 240)
    assert abs(conform_shift(r, Fraction(1))) <= Fraction(49, 100) / r  # clamped
    # Past the end of the media: the last source frame, never an empty piece.
    tail = pieces(1_800_000, 1_810_000, TB, _files(), Fraction(1, 30))
    assert len(tail) == 1
    assert tail[0].end - tail[0].start == Fraction(1, 30)


def test_destination_sizes_framing_and_the_edit_key() -> None:
    """ADR 0046: the edit's aspect and resolution shape the render, not the edit."""
    from mosaic.editing.request import EditRequest
    from mosaic.render.plan import dominant_shape, frame_size, framing, profile

    assert frame_size("16:9", 720) == (1280, 720)
    assert frame_size("16:9", 1080) == (1920, 1080)
    assert frame_size("9:16", 1080) == (1080, 1920)
    assert frame_size("4:5", 1080) == (1080, 1350)
    assert frame_size("1:1", 720) == (720, 720)
    assert frame_size("2.39:1", 1080) == (2582, 1080)
    # The long side is capped at 4096 px, so every H.264 encoder can take the frame.
    assert frame_size("2.39:1", 2160) == (4096, 1714)
    assert frame_size("9:16", 2160) == (2160, 3840)
    assert frame_size("16:9", 2160) == (3840, 2160)
    for aspect in ("16:9", "9:16", "4:5", "1:1", "2.39:1"):
        w, h = frame_size(aspect, 2160)
        assert max(w, h) <= 4096
        assert (w // 16 + (w % 16 > 0)) * (h // 16 + (h % 16 > 0)) <= 36864, "level 5.2"
    # The defaults keep M0/M1 renders exactly as they were.
    assert (profile("preview", ["h264_videotoolbox"]).width, profile("preview", ["x"]).height) == (
        1280,
        720,
    )
    final = profile("final", ["x"], aspect="9:16", resolution="4k")
    assert (final.width, final.height, final.bitrate) == (2160, 3840, "45M")
    assert framing(1920, 1080, 1920, 1080) == "crop"
    assert framing(1920, 1200, 1920, 1080) == "crop", "16:10 into 16:9: within 25 %"
    assert framing(1440, 1080, 1920, 1080) == "fit", "4:3 into 16:9 keeps its bars"
    assert framing(1080, 1920, 1920, 1080) == "fit", "portrait in landscape stays whole"
    assert framing(1080, 1920, 1080, 1920) == "crop"
    assert framing(None, None, 1920, 1080) == "fit"
    # A reel from landscape footage is not that footage's shape: every clip is cropped
    # (PRODUCT.md §4: centre crop in v1), a portrait clip included.
    landscape = Fraction(16, 9)
    reel = profile("preview", ["x"], aspect="9:16", native=landscape)
    assert reel.fill == "crop"
    assert framing(1920, 1080, reel.width, reel.height, reel.fill) == "crop"
    assert profile("preview", ["x"], native=landscape).fill == "auto"
    assert profile("preview", ["x"], native=Fraction(8, 5)).fill == "auto", "16:10: within 25 %"
    assert profile("preview", ["x"], native=Fraction(4, 3)).fill == "crop", "4:3 footage"
    assert profile("preview", ["x"], aspect="1:1").fill == "auto", "unknown footage"
    assert dominant_shape([(1920, 1080, 100), (1080, 1920, 60), (None, None, 500)]) == landscape
    assert dominant_shape([(1080, 1920, 100), (1920, 1080, 60)]) == Fraction(9, 16)
    assert dominant_shape([(None, None, 5)]) is None
    a = EditRequest(duration_s=60)
    b = EditRequest(duration_s=60, aspect="9:16", resolution="4k")
    assert a.key_dump() == b.key_dump(), "changing the shape re-renders, never re-plans"
    assert a.key_dump() != EditRequest(duration_s=90).key_dump()


def test_crop_framing_fills_the_frame() -> None:
    from mosaic.media.ffmpeg import render as rb

    spec = rb.ChunkSpec(
        pieces=[],
        video_index=0,
        audio_index=None,
        audio_enabled=False,
        gain_db=0,
        fade_in=Fraction(0),
        fade_out=Fraction(0),
        width=1080,
        height=1920,
        rate=Fraction(30),
        frames=30,
        samples=48000,
        hdr=None,
        full_range=False,
        encoder="ffv1",
        bitrate="1M",
        out=Path("x.mov"),
        framing="crop",
    )
    chain = rb._video_chain(spec, "[0:v]")
    assert "force_original_aspect_ratio=increase" in chain
    assert "crop=w=1080:h=1920" in chain
    assert ",pad=" not in chain, "no bars: the frame is filled"
    fit = rb._video_chain(replace(spec, framing="fit"), "[0:v]")
    assert "pad=w=1080:h=1920" in fit
