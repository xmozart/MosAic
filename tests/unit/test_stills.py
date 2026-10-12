"""Stills (ADR 0075): the canvas, its motion, the still chunk, and how the solver and
refiner time a photo."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image

from mosaic.editing import refiner, solver
from mosaic.editing.request import pace_frames
from mosaic.editing.retrieval import Candidate
from mosaic.media.ffmpeg.render import StillSpec, still_chunk
from mosaic.media.stills import canvas, canvas_size, covers, motion_exprs

RATE = "30000/1001"


def _photo(path: Path, w: int, h: int, orientation: int = 1) -> Path:
    a = (np.indices((h, w)).sum(axis=0) % 256).astype("uint8")
    img = Image.fromarray(np.stack([a, 255 - a, a // 2], -1))
    ex = Image.Exif()
    ex[0x0112] = orientation
    img.save(path, exif=ex.tobytes(), quality=92)
    return path


def test_the_canvas_has_the_outputs_shape_and_room_to_move() -> None:
    assert canvas_size(1280, 720) == (1920, 1080)
    assert canvas_size(3840, 2160) == (5760, 3240)
    w, h = canvas_size(5000, 2000)
    assert w == 6144, "the long side is capped"
    assert abs(Fraction(w, h) - Fraction(5, 2)) < Fraction(1, 100)
    assert covers(4000, 3000, 1920, 1080), "4:3 fills 16:9"
    assert covers(6000, 4000, 1920, 1080), "3:2 too"
    assert not covers(3000, 4000, 1920, 1080)


def test_a_landscape_photo_fills_and_a_rotated_one_sits_on_a_blurred_fill(tmp_path: Path) -> None:
    wide = canvas(_photo(tmp_path / "wide.jpg", 640, 480), 1280, 720)
    assert wide.size == (1920, 1080)
    # Stored 640×480 with orientation 6: shown upright, 480×640, so not a cover.
    tall = canvas(_photo(tmp_path / "tall.jpg", 640, 480, orientation=6), 1280, 720)
    assert tall.size == (1920, 1080)
    px = np.asarray(tall.convert("L")).astype(np.int32)
    detail = np.abs(np.diff(px, axis=1)).mean(axis=0)
    centre, side = detail[800:1100].mean(), detail[:200].mean()
    assert centre > 4 * side, (centre, side)
    # The photo spans the full height (scaled to fit, never stretched): 1080 × 3/4 wide.
    sharp = np.where(detail > 4 * side)[0]
    assert abs((sharp.max() - sharp.min()) - 810) < 40


def test_motion_expressions_ease_between_the_rectangles() -> None:
    zoom, x, y = motion_exprs(
        {
            "start": {"x": 0, "y": 0, "w": 1000, "h": 1000},
            "end": {"x": 75, "y": 75, "w": 850, "h": 850},
            "easing": "ease_in_out",
        },
        91,
    )
    assert zoom == "(1000/(1000+(-150)*((1-cos(PI*(on/90)))/2)))"
    assert x == "(iw*(0+(75)*((1-cos(PI*(on/90)))/2))/1000)"
    assert y.startswith("(ih*")


def test_the_still_chunk_uses_zoompan_and_never_a_gpl_filter(tmp_path: Path) -> None:
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
    )
    cmd = still_chunk(spec)
    assert "zoompan=" in (cmd.filter_complex or "")
    assert "trim=end_frame=90" in (cmd.filter_complex or "")
    for gpl in ("boxblur", "drawtext", "frei0r"):
        assert gpl not in (cmd.filter_complex or "")
    assert cmd.inputs[0].options[:1] == [("-loop", 1)]


def _still(order: int = 0) -> solver.Shot:
    c = Candidate(
        segment_id=1,
        asset_id=21,
        shot_id=1,
        tb="1/1",
        rate=None,
        start=0,
        end=0,
        usable_start=0,
        usable_end=0,
        has_speech=False,
        status="USE",
        user_use=False,
        capture=None,
        day=1,
        quality=0.5,
        group_id=None,
        shake_percentile=None,
        still=True,
    )
    return solver.Shot(c, "b1", 0, order, "b_roll", 3, "medium", "mute", "r")


def test_a_still_holds_two_to_five_seconds_and_keeps_no_source_range() -> None:
    sh = _still()
    pace = pace_frames("very_fast", RATE)
    lo, hi = solver.bounds(sh, pace, RATE)
    assert (lo, hi) == (60, 150)  # 2 s and 5 s at 29.97
    sh.lo, sh.hi, sh.frames = lo, hi, 90
    cut = refiner.refine(sh, refiner.ClipContext(), pace, RATE)
    assert (cut.src_in, cut.src_out, cut.frames) == (0, 0, 90)
    left = refiner.land_on_target([cut], 100, RATE, pace)
    assert left == 0
    assert cut.frames == 100
    assert (cut.src_in, cut.src_out) == (0, 0)
    assert refiner.land_on_target([cut], 400, RATE, pace) == 400 - 150, "never past 5 s"
    e = refiner.events([cut], RATE)[0]
    assert e["kind"] == "still"
    assert e["source_in"] == e["source_out"] == {"ticks": 0, "tb": "1/1"}
    assert e["duration"] == {"frames": 150, "rate": RATE}
    assert e["audio"]["source_enabled"] is False
    assert e["motion"]["easing"] == "ease_in_out"


def test_an_unreadable_photo_is_a_clear_error(tmp_path: Path) -> None:
    import pytest

    from mosaic.media.photo import PhotoError

    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    with pytest.raises(PhotoError):
        canvas(bad, 1280, 720)
    with pytest.raises(ValueError, match="frame's shape"):
        motion_exprs({"start": {"x": 0, "y": 0, "w": 1000, "h": 900}, "end": FULL}, 10)


FULL = {"x": 0, "y": 0, "w": 1000, "h": 1000}


def test_stills_never_count_toward_the_renders_shape(tmp_path: Path) -> None:
    from mosaic.render.service import _native
    from mosaic.storage import provenance
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_project import Asset
    from mosaic.storage.projects import init_project

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with p.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="t"))
        video = Asset(
            kind="video",
            status="ok",
            profile="generic",
            group_key="v",
            created_at="x",
            provenance_id=prov,
            display_width=1920,
            display_height=1080,
        )
        photo = Asset(
            kind="photo",
            status="ok",
            profile="generic",
            group_key="p",
            created_at="x",
            provenance_id=prov,
            display_width=3000,
            display_height=4000,
        )
        s.add_all([video, photo])
        s.flush()
        events = [
            {
                "asset_id": f"ast_{video.id:04d}",
                "kind": "video",
                "timeline_in": {"frames": 0},
                "timeline_out": {"frames": 30},
            },
            {
                "asset_id": f"ast_{photo.id:04d}",
                "kind": "still",
                "timeline_in": {"frames": 30},
                "timeline_out": {"frames": 330},
            },
        ]
        assert _native(s, events) == Fraction(16, 9), "mostly stills, still a 16:9 video edit"
    p.close()
