"""J- and L-cuts (ADR 0077): only picture cuts move, every heard window stays, the edit's
length is unchanged, and a split version renders its sound from audio chunks."""

from __future__ import annotations

import itertools
from fractions import Fraction
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.core.time import Rounding
from mosaic.editing import refiner
from mosaic.editing.request import pace_frames
from mosaic.editing.retrieval import Candidate
from mosaic.media.ffmpeg.render import AudioSpec, Piece, assemble, audio_chunk
from mosaic.render.plan import audio_span, is_split
from tests.unit.test_editing import RATE, SEC, TB, cand, shot

PACE = pace_frames("balanced", RATE)  # 45 frames minimum
ONE_S = 29  # 1 s at 29.97, whole frames


def _cut(c: Candidate, a_s: float, frames: int, **kw: Any) -> refiner.Cut:
    s = shot(c, **kw)
    s.hi = kw.get("hi", 240)
    a = int(a_s * SEC)
    b = a + refiner.ticks_for_frames(frames, RATE, Fraction(1, 90000), Rounding.CEIL)
    return refiner.Cut(s, a, b, frames, refiner.ClipContext(), [s.selection_ref])


def _talk(sid: int, asset: int, frames: int = 240, **kw: Any) -> refiner.Cut:
    return _cut(cand(sid, asset=asset, speech=True, length_s=20), 2, frames, audio="dialogue", **kw)


def _view(sid: int, asset: int, frames: int = 150, start: float = 4, **kw: Any) -> refiner.Cut:
    return _cut(cand(sid, asset=asset, length_s=20), start, frames, **kw)


def _windows(cuts: list[refiner.Cut]) -> list[tuple[int, int]]:
    return [c.heard for c in cuts]


def test_into_dialogue_a_j_cut_and_out_of_it_an_l_cut() -> None:
    cuts = [_view(1, 1), _talk(2, 2), _view(3, 3)]
    heard = _windows(cuts)
    total = sum(c.frames for c in cuts)
    notes = refiner.split_dialogue(cuts, RATE, PACE)
    assert [n.split(":")[1].split()[0] for n in notes] == ["J-cut", "L-cut"]
    assert _windows(cuts) == heard, "what is heard never moves"
    assert sum(c.frames for c in cuts) == total
    assert [c.frames for c in cuts] == [150 + ONE_S, 240 - 2 * ONE_S, 150 + ONE_S]
    view, talk, after = cuts
    assert (view.head, view.tail) == (0, -ONE_S)
    assert (talk.head, talk.tail) == (ONE_S, ONE_S)
    assert (after.head, after.tail) == (-ONE_S, 0)
    # The neighbours' pictures grow towards the speaker; the speaker's shrinks inside.
    assert view.src_in == heard[0][0]
    assert view.src_out > heard[0][1]
    assert after.src_out == heard[2][1]
    assert after.src_in < heard[2][0]
    assert heard[1][0] < talk.src_in < talk.src_out < heard[1][1]
    events = refiner.events(cuts, RATE)
    assert is_split({"tracks": [{"events": events}]})
    # Sound and picture each cover the timeline exactly, end to end.
    pos = apos = 0
    for e in events:
        assert e["timeline_in"]["frames"] == pos
        pos = e["timeline_out"]["frames"]
        _, _, frames = audio_span(e)
        start = e["audio"].get("timeline_in", e["timeline_in"])["frames"]
        assert start == apos
        apos = start + frames
    assert pos == apos == total
    assert events[1]["audio"]["source_in"] == {"ticks": heard[1][0], "tb": TB}


def test_the_split_is_at_most_a_second_and_a_quarter_of_the_speaker() -> None:
    cuts = [_view(1, 1), _talk(2, 2, frames=100)]
    refiner.split_dialogue(cuts, RATE, PACE)
    assert cuts[1].head == 25, "a quarter of 100 frames"
    short = [_view(1, 1), _talk(2, 2, frames=50)]
    assert refiner.split_dialogue(short, RATE, PACE) == [], "the speaker keeps its minimum"


def test_no_split_where_a_cut_must_stay() -> None:
    def none(cuts: list[refiner.Cut]) -> None:
        before = [(c.src_in, c.src_out, c.frames) for c in cuts]
        assert refiner.split_dialogue(cuts, RATE, PACE) == []
        assert [(c.src_in, c.src_out, c.frames) for c in cuts] == before
        assert all(c.audio is None for c in cuts)

    none([_view(1, 1), _talk(2, 2, locked=True)])
    none([_view(1, 1, locked=True), _talk(2, 2)])
    none([_view(1, 2), _talk(2, 2)])  # one recording: jump-cut rules
    none([_talk(1, 1), _talk(2, 2)])  # two speakers: a straight cut
    none([_view(1, 1), _view(2, 2)])
    # The neighbour has no picture left after its out point.
    edge = _cut(cand(1, asset=1, length_s=5), 0, 149)
    none([edge, _talk(2, 2)])


def test_a_still_neighbour_holds_longer_within_its_five_seconds() -> None:
    photo = _view(1, 1, frames=90)
    photo.shot.cand.still = True
    photo.src_in = photo.src_out = 0
    photo.shot.hi = 110
    cuts = [photo, _talk(2, 2)]
    refiner.split_dialogue(cuts, RATE, PACE)
    assert (photo.frames, photo.src_in, photo.src_out) == (110, 0, 0)
    assert cuts[1].head == 20
    e = refiner.events(cuts, RATE)[0]
    assert e["audio"]["timeline_out"] == {"frames": 90, "rate": RATE}


@settings(max_examples=80, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.integers(30, 300), st.integers(0, 9)),
        min_size=1,
        max_size=10,
    )
)
def test_splits_keep_length_sound_and_ranges(specs: list[tuple[bool, int, int]]) -> None:
    cuts = [
        (_talk if talk else _view)(i + 1, i + 1, frames=frames, **({} if talk else {"start": s}))
        for i, (talk, frames, s) in enumerate(specs)
    ]
    heard = _windows(cuts)
    before = [c.frames for c in cuts]
    refiner.split_dialogue(cuts, RATE, PACE)
    assert _windows(cuts) == heard
    assert sum(c.frames for c in cuts) == sum(before)
    for c, n in zip(cuts, before, strict=True):
        assert c.ua <= c.src_in < c.src_out <= c.ub
        assert c.frames + c.head + c.tail == n, "the sound keeps its own length"
        assert abs(c.head) <= ONE_S
        assert abs(c.tail) <= ONE_S
        if c.shot.dialogue:
            assert c.frames >= min(n, PACE.min)
    for a, b in itertools.pairwise(cuts):
        assert a.tail == -b.head, "one boundary, one offset"
    events = refiner.events(cuts, RATE)
    starts = [e["audio"].get("timeline_in", e["timeline_in"])["frames"] for e in events]
    ends = [e["audio"].get("timeline_out", e["timeline_out"])["frames"] for e in events]
    assert starts[0] == 0
    assert ends[-1] == sum(before)
    assert starts[1:] == ends[:-1]


def test_an_audio_chunk_is_exact_and_silent_without_a_source(tmp_path: Path) -> None:
    silent = audio_chunk(AudioSpec([], None, 0, Fraction(0), Fraction(0), 4004, tmp_path / "a.mov"))
    assert silent.inputs == []
    assert "anullsrc" in (silent.filter_complex or "")
    assert "atrim=end_sample=4004" in (silent.filter_complex or "")
    piece = Piece(tmp_path / "src.mp4", Fraction(2), Fraction(3), Fraction(0))
    cmd = audio_chunk(
        AudioSpec([piece], 1, -6, Fraction(1, 15), Fraction(1, 15), 48000, tmp_path / "b.mov")
    )
    fc = cmd.filter_complex or ""
    assert "[0:1]atrim=start=2.000000:end=3.000000" in fc
    assert "volume=-6dB" in fc
    assert "afade=t=out" in fc
    for gpl in ("boxblur", "drawtext", "frei0r"):
        assert gpl not in fc
    argv = assemble(
        tmp_path / "v.txt",
        tmp_path / "o.mp4",
        None,
        "mp4",
        9000,
        Fraction(30000, 1001),
        tmp_path / "a.txt",
    ).argv(Path("ffmpeg"))
    assert argv.count("concat") == 2
    assert argv[argv.index("1:a:0") - 1] == "-map"


def test_an_l_cut_never_starts_the_neighbour_on_a_camera_jolt() -> None:
    after = _view(3, 3)
    jolt = (after.src_in - 20 * 3003, after.src_in - 10 * 3003)  # 10 frames, ending 10 early
    calm = [(after.src_in + i * 3003, after.src_in + (i + 1) * 3003, 0.001) for i in range(9)]
    after.ctx = refiner.ClipContext(motion=[(*jolt, 0.5), *calm])
    cuts = [_talk(2, 2), after]
    refiner.split_dialogue(cuts, RATE, PACE)
    assert after.head == -10, "the picture starts after the jolt"
    assert after.src_in >= jolt[1]
    # A jolt right at the in point leaves nothing to grow into: no split.
    close = _view(4, 4)
    close.ctx = refiner.ClipContext(motion=[(close.src_in - 3 * 3003, close.src_in, 0.5), *calm])
    assert refiner.split_dialogue([_talk(2, 2), close], RATE, PACE) == []


def test_a_neighbour_grows_no_longer_than_its_pace() -> None:
    long = _view(1, 1, frames=PACE.max - 10, start=1)
    long.shot.hi = PACE.max - 10
    cuts = [long, _talk(2, 2)]
    refiner.split_dialogue(cuts, RATE, PACE)
    assert long.frames == PACE.max


def test_moved_in_points_sit_on_the_source_frame_grid() -> None:
    cuts = [_view(1, 1), _talk(2, 2), _view(3, 3)]
    refiner.split_dialogue(cuts, RATE, PACE)
    for c in cuts:
        assert c.src_in % 3000 == 0, "30 fps source: a frame every 3000 ticks"


def test_a_split_events_picture_chunk_is_reused_wherever_it_sits() -> None:
    from mosaic.render.plan import Profile, audio_key, chunk_key

    cuts = [_view(1, 1), _talk(2, 2), _view(3, 3)]
    refiner.split_dialogue(cuts, RATE, PACE)
    here = refiner.events(cuts, RATE)[1]
    later = refiner.events([_view(9, 9, frames=200), *cuts], RATE)[2]
    assert here["audio"]["timeline_in"] != later["audio"]["timeline_in"]
    prof = Profile("preview", 1280, 720, "ffv1", "5M", lossless=True)
    assert chunk_key("p", here, ["f"], prof, RATE) == chunk_key("p", later, ["f"], prof, RATE)
    assert audio_key("p", here, ["f"], prof, RATE) == audio_key("p", later, ["f"], prof, RATE)
    plain = refiner.events([_view(1, 1)], RATE)[0]
    moved = plain | {"audio": plain["audio"] | {"gain_db": -3}}
    assert chunk_key("p", plain, ["f"], prof, RATE) != chunk_key("p", moved, ["f"], prof, RATE)
