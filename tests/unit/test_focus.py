"""Subject focus (ADR 0076): saliency points, which frames are read, and how crops and
still motion use the point."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from mosaic.editing.refiner import PUSHED, pushed, transform
from mosaic.library.focus import frames_for
from mosaic.media.ffmpeg.render import crop_origin
from mosaic.media.saliency import focus_point


def _subject_at(cx: float, cy: float) -> Image.Image:
    img = Image.new("RGB", (640, 360), (90, 120, 160))
    d = ImageDraw.Draw(img)
    x, y = cx * 640, cy * 360
    d.ellipse((x - 40, y - 40, x + 40, y + 40), fill=(250, 200, 30))
    return img


def test_the_focus_is_on_what_stands_out() -> None:
    for cx, cy in ((0.25, 0.5), (0.75, 0.3), (0.5, 0.8)):
        point = focus_point([_subject_at(cx, cy)])
        assert point is not None
        x, y = point
        assert abs(x - cx * 1000) < 40, (cx, point)
        assert abs(y - cy * 1000) < 40, (cy, point)
    noise = Image.fromarray((np.random.default_rng(1).random((360, 640, 3)) * 255).astype("uint8"))
    flat = focus_point([noise])
    assert flat is not None
    assert all(abs(c - 500) < 30 for c in flat), "nothing stands out: the centre"
    assert focus_point([]) is None
    # Frames of one segment average to one steady point.
    both = focus_point([_subject_at(0.3, 0.5), _subject_at(0.5, 0.5)])
    assert both is not None
    assert 330 < both[0] < 470


def test_frames_are_spread_over_the_usable_range() -> None:
    samples = [(i, 1, t, f"k{t}") for i, t in enumerate(range(0, 1000, 50))]
    assert frames_for(100, 300, samples) == ["k100", "k150", "k200", "k250"]
    assert frames_for(0, 1000, samples) == ["k0", "k250", "k500", "k750"]
    assert frames_for(0, 0, [(1, 1, 0, "photo")]) == ["photo"]


def test_transforms_and_still_motion_use_the_focus() -> None:
    assert "focus" not in transform(None)
    assert transform((300, 700))["focus"] == {"x": 300, "y": 700}
    assert pushed(None) == PUSHED
    assert pushed((500, 500)) == {"x": 75, "y": 75, "w": 850, "h": 850}
    assert pushed((100, 900)) == {"x": 0, "y": 150, "w": 850, "h": 850}, "kept in frame"


def test_a_crop_centres_on_the_focus_inside_the_picture() -> None:
    assert crop_origin(None) == ("(iw-ow)/2", "(ih-oh)/2")
    x, y = crop_origin((250, 600))
    assert x == "max(0,min(iw-ow,iw*250/1000-ow/2))"
    assert y == "max(0,min(ih-oh,ih*600/1000-oh/2))"


def test_an_unreadable_frame_is_skipped(tmp_path: Any) -> None:
    from mosaic.library.focus import _read

    class Artifacts:
        def get_bytes(self, kind: str, key: str) -> bytes:
            if key == "gone":
                raise FileNotFoundError(key)
            return b"not an image"

    class Ctx:
        class project:  # noqa: N801 - a stand-in for TaskContext.project
            artifacts = Artifacts()

    assert _read(Ctx(), "gone") is None  # type: ignore[arg-type]
    assert _read(Ctx(), "junk") is None  # type: ignore[arg-type]
