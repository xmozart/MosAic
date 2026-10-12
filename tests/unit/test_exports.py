"""Final profiles and export sidecars (ADR 0084): codecs, containers and the SRT cues."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.editing.captions import Word, _lines, cues, stamp
from mosaic.media.ffmpeg.render import _video_codec, assemble, pix_fmt
from mosaic.render.plan import CODECS, Profile, assembly_key, profile

RATE = Fraction(30000, 1001)


def test_codecs_choose_their_container_and_picture() -> None:
    assert CODECS == ("h264", "hevc", "prores")
    h264 = profile("final", ["h264_videotoolbox"], resolution="4k")
    assert (h264.container, h264.bitrate, h264.codec) == ("mp4", "45M", "h264")
    assert "codec" not in h264.as_json(), "an H.264 profile (and its chunk keys) unchanged"
    hevc = profile("final", ["hevc_videotoolbox"], resolution="4k", codec="hevc")
    assert (hevc.container, hevc.bitrate) == ("mp4", "28M")
    assert hevc.as_json()["codec"] == "hevc"
    master = profile("final", ["prores_ks"], codec="prores")
    assert (master.container, master.bitrate) == ("mov", "")
    assert pix_fmt("prores_ks") == pix_fmt("prores_videotoolbox") == "yuv422p10le"
    assert pix_fmt("hevc_videotoolbox") == "yuv420p"
    assert ("-profile:v", 2) in _video_codec("prores_ks", "", RATE)
    assert not any(k == "-b:v" for k, _ in _video_codec("prores_ks", "", RATE))
    with pytest.raises(RuntimeError, match="HEVC"):
        profile("final", [], codec="hevc")
    preview = profile("preview", ["h264_videotoolbox"], codec="h264")
    assert preview.codec == "h264"


def test_hevc_is_tagged_for_apple_players_and_loudness_is_the_requests(tmp_path: Path) -> None:
    def argv(**kw: object) -> list[str]:
        cmd = assemble(tmp_path / "l.txt", tmp_path / "o.mp4", None, "mp4", 4800, RATE, **kw)  # type: ignore[arg-type]
        return cmd.argv(Path("ffmpeg"))

    assert argv(hevc=True)[argv(hevc=True).index("-tag:v") + 1] == "hvc1"
    assert "-tag:v" not in argv()
    prof = Profile("final", 1920, 1080, "h264_videotoolbox", "14M")
    web = assembly_key("p", ["c"], [], None, prof, "30/1", 90, "-14")
    tv = assembly_key("p", ["c"], [], None, prof, "30/1", 90, "-23")
    assert web != tv
    assert web == assembly_key("p", ["c"], [], None, prof, "30/1", 90), "web is the default"


def _w(a: float, b: float, text: str) -> Word:
    return Word(Fraction(a).limit_denominator(1000), Fraction(b).limit_denominator(1000), text)


def test_cues_close_at_sentences_pauses_and_length() -> None:
    words = [
        _w(0.0, 0.3, "We"), _w(0.3, 0.6, "made"), _w(0.6, 1.0, "it."),
        _w(1.1, 1.4, "Look"), _w(1.4, 1.7, "at"), _w(1.7, 2.0, "that"),
        _w(3.5, 3.9, "waterfall"),  # after a pause
    ]  # fmt: skip
    got = cues(iter(words))
    assert [t for _, _, t in got] == ["We made it.", "Look at that", "waterfall"]
    assert got[0][0] == 0
    assert got[0][1] == 1, "ends with its last word"
    assert got[1][1] == Fraction(21, 10), "a 0.9 s cue is held to a second"
    assert got[2][1] == Fraction(45, 10), "a short last cue is held to a second"
    long = [_w(i * 0.4, i * 0.4 + 0.3, f"word{i:02d}") for i in range(30)]
    for a, b, text in cues(iter(long)):
        assert b - a <= 7
        assert all(len(line) <= 42 for line in text.split("\n"))
        assert text.count("\n") <= 1


def test_srt_times_and_lines() -> None:
    assert stamp(Fraction(3723456, 1000)) == "01:02:03,456"
    assert stamp(Fraction(1, 3)) == "00:00:00,333", "floored to the millisecond"
    assert _lines("short") == "short"
    two = _lines("the quick brown fox jumps over the lazy dog near the river bank")
    assert "\n" in two
    first, second = two.split("\n")
    assert abs(len(first) - len(second)) <= 8


@settings(max_examples=150, deadline=None)
@given(st.fractions(min_value=0, max_value=36000))
def test_a_stamp_is_never_later_than_its_time(t: Fraction) -> None:
    h, m, rest = stamp(t).split(":")
    sec, ms = rest.split(",")
    shown = Fraction(int(h) * 3600 + int(m) * 60 + int(sec)) + Fraction(int(ms), 1000)
    assert shown <= t < shown + Fraction(1, 1000)


@settings(max_examples=150, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(0, 3000),
            st.integers(1, 1500),
            st.text("abcdefgh.!? ", min_size=1, max_size=14),
        ),
        max_size=60,
    )
)
def test_cues_are_ordered_short_and_fit_two_lines(spec: list[tuple[int, int, str]]) -> None:
    words, at = [], Fraction(0)
    for gap, length, text in spec:
        start = at + Fraction(gap, 1000)
        words.append(Word(start, start + Fraction(length, 1000), text.strip() or "x"))
        at = start + Fraction(length, 1000)
    got = cues(iter(words))
    for i, (a, b, text) in enumerate(got):
        assert a < b
        assert text.count("\n") <= 1
        if i + 1 < len(got):
            assert b <= got[i + 1][0], "never into the next cue"
    joined = " ".join(t for _, _, t in got).split()
    assert joined == " ".join(w.text for w in words).split(), "every word, once, in order"


def test_the_exports_loudness_wins_over_the_requests() -> None:
    from types import SimpleNamespace

    from mosaic.render.tasks import _loudness

    def lufs(profile: dict[str, str], request: dict[str, str]) -> str:
        return _loudness(SimpleNamespace(profile=profile), SimpleNamespace(request=request))  # type: ignore[arg-type]

    assert lufs({"loudness": "tv"}, {"loudness": "web"}) == "-23"
    assert lufs({}, {"loudness": "tv"}) == "-23"
    assert lufs({}, {}) == "-14"
