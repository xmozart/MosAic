"""The M4 edit request (PRODUCT.md §4; ADR 0066): every wizard section has a default, a
request saved before M4 still loads, and invalid choices are refused."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.core.timecheck import find_float_times
from mosaic.editing.request import RENDER_ONLY, EditRequest, ShotLengths, pace_frames

M2_REQUEST = {
    "duration_s": 60,
    "story": "nature",
    "chronology": "strict",
    "pace": "slow",
    "tolerance_pct": 5,
    "instructions": "",
    "fps": None,
    "variant": 0,
    "aspect": "16:9",
    "resolution": "1080p",
}


def test_an_m2_request_loads_with_the_wizard_defaults() -> None:
    saved = {"duration_s": 60, "story": "nature", "chronology": "strict", "pace": "slow"}
    req = EditRequest.model_validate(saved)
    assert req.arc == "classic_travel"
    assert req.beats == []
    assert req.weights == {}
    assert req.rules.avoid_repetition
    assert req.photo_share == "some"
    assert req.transitions == "cuts"
    assert req.audio.keep_dialogue
    assert req.loudness == "web"
    assert req.music is None
    assert req.shot_lengths is None


def test_neutral_weights_are_left_out_so_one_request_has_one_key() -> None:
    a = EditRequest(duration_s=60, weights={"wildlife": "strong", "people": "neutral"})
    b = EditRequest(duration_s=60, weights={"wildlife": "strong"})
    assert a.weights == {"wildlife": "strong"}
    assert a.key_dump() == b.key_dump()
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, weights={"wildlife": "lots"})
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, weights={"dinosaurs": "more"})


def test_custom_arc_needs_beats_and_only_it_has_them() -> None:
    req = EditRequest(duration_s=60, arc="custom", beats=[" Arrival ", "The reef", "Home"])
    assert req.beats == ["Arrival", "The reef", "Home"]
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, arc="custom")
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, beats=["Arrival"])
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, arc="custom", beats=["x" * 81])
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, arc="custom", beats=["  "])


def test_advanced_shot_lengths_replace_the_pace_in_frames() -> None:
    req = EditRequest(duration_s=60, shot_lengths={"min_ds": 15, "preferred_ds": 40, "max_ds": 90})
    pace = pace_frames(req.pace, "30/1", req.shot_lengths)
    assert (pace.min, pace.preferred, pace.max) == (45, 120, 270)
    assert pace_frames(req.pace, "30/1") != pace
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, shot_lengths={"min_ds": 50, "preferred_ds": 40, "max_ds": 90})


def test_music_is_a_track_with_a_static_level_and_fades() -> None:
    req = EditRequest(duration_s=60, music={"path": "/trips/Horizon.mp3"})
    assert req.music is not None
    assert (req.music.level_db, req.music.fade_in_ms, req.music.fade_out_ms) == (-18, 2000, 3000)
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, music={"path": "/x.mp3", "level_db": 6})
    with pytest.raises(ValidationError):
        EditRequest(duration_s=60, music={"path": "/x.mp3", "beat_sync": True})


def test_loudness_is_render_only_and_nothing_is_a_float() -> None:
    assert "loudness" in RENDER_ONLY
    web = EditRequest(duration_s=60)
    tv = EditRequest(duration_s=60, loudness="tv")
    assert web.key_dump() == tv.key_dump()
    full = EditRequest(
        duration_s=60,
        weights={"drone": "more"},
        shot_lengths={"min_ds": 10, "preferred_ds": 30, "max_ds": 60},
        music={"path": "/m.mp3"},
    )
    assert find_float_times(full.model_dump(mode="json")) == []


def test_an_m2_request_keeps_its_key_and_its_edit(tmp_path: Path) -> None:
    from mosaic.editing.service import create_edit
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_project import Edit
    from mosaic.storage.projects import init_project

    req = EditRequest.model_validate(M2_REQUEST)
    before_m4 = {k: v for k, v in M2_REQUEST.items() if k not in ("aspect", "resolution")}
    assert req.key_dump() == before_m4, "the key an M2 edit was made with"
    assert EditRequest.model_validate({**M2_REQUEST, "photo_share": "many"}).key_dump() != (
        before_m4
    )
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    with project.write() as s:
        old = Edit(uid="01OLD", name="old", request=dict(M2_REQUEST), created_at="x")
        s.add(old)
        s.flush()
        old_id = old.id
    assert create_edit(project, req, control, control.local_principal) == old_id
    other = EditRequest.model_validate({**M2_REQUEST, "transitions": "dissolves"})
    assert create_edit(project, other, control, control.local_principal) != old_id
    project.close()


RATES = st.sampled_from(["24000/1001", "24/1", "25/1", "30000/1001", "30/1", "60000/1001", "60/1"])


@st.composite
def _lengths(draw: st.DrawFn) -> ShotLengths:
    lo = draw(st.integers(3, 600))
    pref = draw(st.integers(lo, 600))
    hi = draw(st.integers(max(pref, 3), 1200))
    return ShotLengths(min_ds=lo, preferred_ds=pref, max_ds=hi)


@given(_lengths(), RATES, st.sampled_from(["very_slow", "balanced", "very_fast"]))
def test_shot_lengths_in_frames(lengths: ShotLengths, rate: str, pace: str) -> None:
    got = pace_frames(pace, rate, lengths)
    r = parse_rational(rate)

    def frames(ds: int) -> int:
        return round_fraction(Fraction(ds, 10) * r, Rounding.NEAREST)

    assert (got.min, got.preferred, got.max) == (
        frames(lengths.min_ds),
        frames(lengths.preferred_ds),
        frames(lengths.max_ds),
    )
    assert got.min <= got.preferred <= got.max
    assert got.dialogue_max >= got.max, "dialogue may always run as long as any shot"
    assert got.dialogue_max >= frames(200)
