"""Transitions (ADR 0078): dips at the opening and closing, dissolves where a beat
changes, the frames that render them, and the dissolve chunk."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.core.time import frame_start_ticks
from mosaic.editing import refiner
from mosaic.media.ffmpeg.render import ChunkSpec, Piece, chunk, dissolve_chunk
from mosaic.render.plan import (
    chunk_key,
    dips,
    dissolve_frames,
    dissolve_sides,
    fades,
    picture,
)
from tests.unit.test_editing import RATE, cand
from tests.unit.test_jl_cuts import PACE, _cut, _talk

RATE_F = Fraction(30000, 1001)
HALF = 7  # a quarter of a second at 29.97: half of a 14-frame dissolve
DIP = 15


def _beats(*beats: str) -> list[refiner.Cut]:
    return [
        _cut(cand(i + 1, asset=i + 1, length_s=20), 4, 150, beat=b) for i, b in enumerate(beats)
    ]


def _timeline(cuts: list[refiner.Cut]) -> dict[str, object]:
    events = refiner.events(cuts, RATE)
    return {"rate": RATE, "tracks": [{"kind": "video", "events": events}]}


def test_cuts_dip_only_at_the_opening_and_closing() -> None:
    cuts = _beats("b1", "b2", "b3")
    refiner.choose_transitions(cuts, "cuts", RATE)
    events = refiner.events(cuts, RATE)
    assert events[0]["transition_in"] == {"type": "dip", "frames": DIP, "rate": RATE}
    assert events[-1]["transition_out"] == {"type": "dip", "frames": DIP, "rate": RATE}
    assert [e["transition_out"]["type"] for e in events] == ["cut", "cut", "dip"]
    assert "transition_in" not in events[1]
    plain = _beats("b1", "b2")
    refiner.choose_transitions(plain, "minimal", RATE)
    assert all(
        e["transition_out"] == {"type": "cut"} and "transition_in" not in e
        for e in refiner.events(plain, RATE)
    )


def test_dissolves_where_a_beat_changes_with_picture_to_spare() -> None:
    cuts = _beats("b1", "b1", "b2", "b3")
    total = sum(c.frames for c in cuts)
    refiner.choose_transitions(cuts, "dissolves", RATE)
    assert [c.dissolve for c in cuts] == [0, 2 * HALF, 2 * HALF, 0]
    assert sum(c.frames for c in cuts) == total, "a dissolve never changes the length"
    # No picture past the out point: a cut.
    edge = _beats("b1", "b2")
    edge[0].ub = edge[0].src_out
    notes = refiner.choose_transitions(edge, "dissolves", RATE)
    assert edge[0].dissolve == 0
    assert "no picture to dissolve over" in notes[0]
    # A photo: a cut.
    photo = _beats("b1", "b2")
    photo[1].shot.cand.still = True
    refiner.choose_transitions(photo, "dissolves", RATE)
    assert photo[0].dissolve == 0


def test_a_dissolve_boundary_gets_no_j_or_l_cut() -> None:
    view = _cut(cand(1, asset=1, length_s=20), 4, 150, beat="b1")
    talk = _talk(2, 2, beat="b2")
    cuts = [view, talk]
    refiner.choose_transitions(cuts, "dissolves", RATE)
    assert view.dissolve
    assert refiner.split_dialogue(cuts, RATE, PACE) == []


def test_each_picture_renders_less_half_of_each_dissolve() -> None:
    cuts = _beats("b1", "b2", "b3")
    refiner.choose_transitions(cuts, "dissolves", RATE)
    tl = _timeline(cuts)
    events = tl["tracks"][0]["events"]  # type: ignore[index]
    shown = [picture(tl, i) for i in range(3)]
    lengths = [p["timeline_out"]["frames"] - p["timeline_in"]["frames"] for p in shown]
    assert lengths == [150 - HALF, 150 - 2 * HALF, 150 - HALF]
    side_a, side_b, n = dissolve_sides(tl, 0)
    assert n == 2 * HALF
    # The pictures and the dissolve tile the timeline and the source without a gap.
    assert side_a["timeline_in"] == shown[0]["timeline_out"]
    assert side_a["timeline_out"] == shown[1]["timeline_in"]
    assert side_a["source_in"] == shown[0]["source_out"]
    assert side_b["source_out"] == shown[1]["source_in"]
    assert side_b["source_in"]["ticks"] < events[1]["source_in"]["ticks"], "a handle"
    assert side_a["audio"]["fade_out_frames"] == n
    assert side_b["audio"]["fade_in_frames"] == n
    assert shown[0]["audio"]["fade_out_frames"] == 0, "the dissolve carries the sound on"
    assert shown[1]["audio"]["fade_in_frames"] == 0
    assert dissolve_frames(events[0]) == n
    assert dips(shown[0]) == {"dip_in": DIP}
    assert dips(shown[2]) == {"dip_out": DIP}
    assert dips(shown[1]) == {}


def test_an_event_without_a_transition_keeps_its_chunk_key() -> None:
    from mosaic.render.plan import Profile

    cuts = _beats("b1", "b1", "b1")
    tl_cut = _timeline(cuts)
    refiner.choose_transitions(cuts, "cuts", RATE)
    tl_dip = _timeline(cuts)
    prof = Profile("preview", 1280, 720, "ffv1", "5M", lossless=True)

    def key(tl: dict[str, object], i: int) -> str:
        return chunk_key("p", picture(tl, i), ["f"], prof, RATE)

    assert key(tl_cut, 1) == key(tl_dip, 1)
    assert key(tl_cut, 0) != key(tl_dip, 0)


def test_the_dissolve_chunk_blends_with_xfade_and_mixes_the_sound(tmp_path: Path) -> None:
    def spec(name: str, fade_in: int, fade_out: int) -> ChunkSpec:
        return ChunkSpec(
            pieces=[Piece(tmp_path / f"{name}.mp4", Fraction(1), Fraction(2), Fraction(0))],
            video_index=0,
            audio_index=1,
            audio_enabled=True,
            gain_db=0,
            fade_in=Fraction(fade_in, 30),
            fade_out=Fraction(fade_out, 30),
            width=1280,
            height=720,
            rate=Fraction(30000, 1001),
            frames=14,
            samples=22422,
            hdr=None,
            full_range=False,
            encoder="ffv1",
            bitrate="5M",
            out=tmp_path / f"{name}.mov",
        )

    cmd = dissolve_chunk(spec("a", 0, 14), spec("b", 14, 0), tmp_path / "d.mov")
    fc = cmd.filter_complex or ""
    assert "[va][vb]xfade=transition=fade" in fc
    assert "[1:0]trim" in fc, "the second side reads its own input"
    assert "[1:1]atrim" in fc
    assert "amix=inputs=2:normalize=0" in fc
    for gpl in ("boxblur", "drawtext", "frei0r"):
        assert gpl not in fc
    dipped = spec("c", 0, 0)
    dipped.frames, dipped.dip_in, dipped.dip_out = 60, 15, 15
    assert "fade=t=in:s=0:n=15" in (chunk(dipped).filter_complex or "")
    assert "fade=t=out:s=45:n=15" in (chunk(dipped).filter_complex or "")


@settings(max_examples=150, deadline=None)
@given(
    st.sampled_from(["24/1", "25/1", "30000/1001", "60/1"]),
    st.sampled_from(["1/90000", "1/600", "1/48000", "1/30000"]),
    st.lists(st.integers(40, 400), min_size=2, max_size=6),
    st.lists(st.booleans(), min_size=5, max_size=5),
    st.integers(1, 15),
)
def test_pictures_and_dissolves_tile_timeline_and_source(
    rate: str, tb: str, lengths: list[int], where: list[bool], half: int
) -> None:
    """Whatever the rates, each event's picture plus half of each dissolve it takes part
    in is exactly its frames, and the source windows meet where they should."""
    events = []
    pos = 0
    for i, n in enumerate(lengths):
        start = 10_000_000 + 7919 * i
        e = {
            "event_id": f"evt_{i + 1:04d}",
            "kind": "video",
            "source_in": {"ticks": start, "tb": tb},
            "source_out": {"ticks": start + frame_start_ticks(n, rate, tb), "tb": tb},
            "timeline_in": {"frames": pos, "rate": rate},
            "timeline_out": {"frames": pos + n, "rate": rate},
            "audio": {"fade_in_frames": 2, "fade_out_frames": 2},
            "transition_out": {"type": "cut"},
        }
        if i < len(lengths) - 1 and where[i] and n > 4 * half and lengths[i + 1] > 4 * half:
            e["transition_out"] = {"type": "dissolve", "frames": 2 * half, "rate": rate}
        events.append(e)
        pos += n
    tl = {"rate": rate, "tracks": [{"kind": "video", "events": events}]}
    rendered = 0
    for i, e in enumerate(events):
        p = picture(tl, i)
        rendered += p["timeline_out"]["frames"] - p["timeline_in"]["frames"]
        if not dissolve_frames(e):
            continue
        a, b, n = dissolve_sides(tl, i)
        rendered += n
        assert a["timeline_in"] == p["timeline_out"]
        assert a["source_in"] == p["source_out"]
        assert a["source_out"]["ticks"] == e["source_out"]["ticks"] + frame_start_ticks(
            half, rate, tb
        ), "the outgoing handle is the one the refiner checked"
        nxt = events[i + 1]
        assert b["source_in"]["ticks"] == nxt["source_in"]["ticks"] - frame_start_ticks(
            half, rate, tb
        )
        assert b["source_out"] == picture(tl, i + 1)["source_in"]
        assert b["timeline_out"] == picture(tl, i + 1)["timeline_in"]
    assert rendered == pos, "pictures and dissolves add up to the edit"


def test_an_odd_dissolve_is_refused() -> None:
    cuts = _beats("b1", "b2")
    tl = _timeline(cuts)
    tl["tracks"][0]["events"][0]["transition_out"] = {  # type: ignore[index]
        "type": "dissolve",
        "frames": 13,
        "rate": RATE,
    }
    with pytest.raises(ValueError, match="even"):
        dissolve_sides(tl, 0)


def test_a_dissolve_never_reads_a_camera_jolt_or_starves_a_picture() -> None:
    cuts = _beats("b1", "b2")
    jolt = (cuts[0].src_out + 2 * 3003, cuts[0].src_out + 9 * 3003)
    calm = [(cuts[0].src_in + k * 3003, cuts[0].src_in + (k + 1) * 3003, 0.001) for k in range(9)]
    cuts[0].ctx = refiner.ClipContext(motion=[(*jolt, 0.5), *calm])
    notes = refiner.choose_transitions(cuts, "dissolves", RATE)
    assert cuts[0].dissolve == 0
    assert "no picture to dissolve over" in notes[0]
    short = _beats("b1", "b2")
    short[1].frames = HALF + DIP // 2  # ends the edit, dips out over half of itself
    notes = refiner.choose_transitions(short, "dissolves", RATE)
    assert short[0].dissolve == 0
    assert "too short to dissolve" in notes[0]


def test_a_short_first_event_dips_over_half_of_itself() -> None:
    cuts = [_cut(cand(1, asset=1, length_s=20), 4, 20), *_beats("b2")]
    refiner.choose_transitions(cuts, "cuts", RATE)
    assert cuts[0].dip_in == 10


def test_a_dip_fades_a_still_and_a_split_events_own_sound(tmp_path: Path) -> None:
    from mosaic.media.ffmpeg.render import StillSpec, still_chunk
    from mosaic.render.plan import Profile, audio_key

    spec = StillSpec(
        tmp_path / "c.png",
        "1",
        "0",
        "0",
        1280,
        720,
        Fraction(30000, 1001),
        90,
        144144,
        "ffv1",
        "5M",
        tmp_path / "o.mov",
        dip_in=15,
    )
    assert "fade=t=in:s=0:n=15" in (still_chunk(spec).filter_complex or "")
    plain_cuts = [_cut(cand(1, asset=1, length_s=20), 4, 150), _talk(2, 2)]
    refiner.split_dialogue(plain_cuts, RATE, PACE)
    plain = refiner.events(plain_cuts, RATE)[0]
    cuts = [_cut(cand(1, asset=1, length_s=20), 4, 150), _talk(2, 2)]
    refiner.choose_transitions(cuts, "cuts", RATE)  # the production order (resolve)
    refiner.split_dialogue(cuts, RATE, PACE)
    dipped = refiner.events(cuts, RATE)[0]
    assert "timeline_in" in dipped["audio"], "the opening event is split"
    prof = Profile("preview", 1280, 720, "ffv1", "5M", lossless=True)
    assert audio_key("p", plain, ["f"], prof, RATE) != audio_key("p", dipped, ["f"], prof, RATE)
    assert fades(plain, RATE) == (Fraction(2) / RATE_F, Fraction(2) / RATE_F)
    assert fades(dipped, RATE) == (Fraction(DIP) / RATE_F, Fraction(2) / RATE_F)


def test_a_dissolve_is_reused_while_neither_picture_changes() -> None:
    from mosaic.render.plan import Profile, dissolve_key

    prof = Profile("preview", 1280, 720, "ffv1", "5M", lossless=True)

    def key(tl: dict[str, object]) -> str:
        a, b, n = dissolve_sides(tl, 0)
        return dissolve_key(
            "p", chunk_key("p", a, ["f"], prof, RATE), chunk_key("p", b, ["f"], prof, RATE), n, RATE
        )

    cuts = _beats("b1", "b2", "b3")
    refiner.choose_transitions(cuts, "dissolves", RATE)
    first = key(_timeline(cuts))
    cuts[2].frames -= 10  # a later event changes
    cuts[2].src_out -= 10 * 3003
    assert key(_timeline(cuts)) == first
    cuts[1].src_in += 3003  # the incoming picture changes
    assert key(_timeline(cuts)) != first
