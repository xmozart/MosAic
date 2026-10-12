"""The music bed (ADR 0080): the track's path, where it ducks, and the mix command."""

from __future__ import annotations

import itertools
import os
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.editing.music import MusicPathError, check_path, speech_windows
from mosaic.media.ffmpeg.render import MusicSpec, duck_expr, music_mix

RATE = "30000/1001"


def test_the_track_is_an_absolute_readable_file(tmp_path: Path) -> None:
    track = tmp_path / "song.mp3"
    track.write_bytes(b"ID3")
    assert check_path(str(track)) == track
    with pytest.raises(MusicPathError, match="full path"):
        check_path("song.mp3")
    with pytest.raises(MusicPathError, match="no such file"):
        check_path(str(tmp_path / "missing.mp3"))
    with pytest.raises(MusicPathError, match="no such file"):
        check_path(str(tmp_path))  # a folder is not a track
    with pytest.raises(MusicPathError, match="Invalid"):
        check_path("/tmp/a\x00b")
    if os.geteuid() != 0:  # root reads anything
        track.chmod(0)
        try:
            with pytest.raises(MusicPathError, match="can't be read"):
                check_path(str(track))
        finally:
            track.chmod(0o600)


def _event(a: int, b: int, intent: str, **audio: object) -> dict[str, object]:
    return {
        "timeline_in": {"frames": a, "rate": RATE},
        "timeline_out": {"frames": b, "rate": RATE},
        "audio": {"intent": intent, "source_enabled": intent != "mute", **audio},
    }


def test_the_music_ducks_under_dialogue_only_and_bridges_short_gaps() -> None:
    events = [
        _event(0, 100, "natural_sound"),
        _event(100, 200, "dialogue"),
        _event(200, 210, "mute"),
        _event(210, 300, "dialogue"),
        _event(300, 600, "natural_sound"),
        # A J-cut: the speech is heard from frame 590, under the previous picture.
        _event(
            600,
            700,
            "dialogue",
            timeline_in={"frames": 590, "rate": RATE},
            timeline_out={"frames": 700, "rate": RATE},
        ),
        {"kind": "title", **_event(700, 790, "mute")},
    ]
    timeline = {"tracks": [{"events": events}]}
    assert speech_windows(timeline, 15) == [(100, 300), (590, 700)]
    assert speech_windows(timeline, 5) == [(100, 200), (210, 300), (590, 700)]
    assert speech_windows({"tracks": [{"events": events[:1]}]}, 15) == []


def test_the_duck_is_a_ramped_envelope_in_time() -> None:
    assert duck_expr([], -12, Fraction(1, 4)) == "1"
    expr = duck_expr([(Fraction(2), Fraction(5)), (Fraction(9), Fraction(10))], -12, Fraction(1, 4))
    assert expr.startswith("1-0.748811*max(clip(")
    assert "(t-2.000000+0.250000)/0.250000" in expr
    assert "(10.000000+0.250000-t)/0.250000" in expr


def test_the_mix_loops_the_track_and_never_normalizes_the_edit(tmp_path: Path) -> None:
    spec = MusicSpec(
        audio=tmp_path / "list.txt",
        audio_concat=True,
        music=tmp_path / "song.mp3",
        samples=480000,
        level_db=-18,
        fade_in=Fraction(2),
        fade_out=Fraction(3),
        duck=[(Fraction(2), Fraction(5))],
        duck_db=-12,
        ramp=Fraction(1, 4),
        out=tmp_path / "mix.mov",
    )
    cmd = music_mix(spec)
    assert cmd.inputs[0].options == [("-f", "concat"), ("-safe", 0)]
    assert cmd.inputs[1].options == [("-stream_loop", -1)]
    fc = cmd.filter_complex or ""
    assert "volume=-18dB" in fc
    assert "afade=t=out:st=7.000000:d=3.000000" in fc
    assert "eval=frame" in fc
    assert "amix=inputs=2:normalize=0:duration=first" in fc
    assert fc.count("atrim=end_sample=480000") == 3
    for gpl in ("boxblur", "drawtext", "frei0r", "sidechaincompress=", "rubberband"):
        assert gpl not in fc
    one_file = music_mix(MusicSpec(**{**spec.__dict__, "audio_concat": False}))
    assert one_file.inputs[0].options == []


@settings(max_examples=150, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(0, 3000), st.integers(1, 400), st.booleans()),
        max_size=12,
    ),
    st.integers(0, 60),
)
def test_speech_windows_are_sorted_apart_and_cover_every_dialogue(
    spans: list[tuple[int, int, bool]], merge: int
) -> None:
    events = [_event(a, a + n, "dialogue" if talk else "natural_sound") for a, n, talk in spans]
    out = speech_windows({"tracks": [{"events": events}]}, merge)
    for (a, b), (c, d) in itertools.pairwise(out):
        assert a < b <= c < d
        assert c - b > merge, "closer windows are joined"
    for a, n, talk in spans:
        if talk:
            assert any(s <= a and a + n <= t for s, t in out)
