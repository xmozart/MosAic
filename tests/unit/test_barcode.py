from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mosaic.devtools import barcode


def _frame(w: int = 320, h: int = 180, index: int = 0) -> np.ndarray:
    f = np.full((h, w, 3), 128, dtype=np.uint8)
    f[h // 2 :, : w // 2] = (90, 150, 110)
    barcode.draw(f, index)
    return f


@given(st.integers(min_value=0, max_value=barcode.MAX_INDEX))
@settings(max_examples=200)
def test_round_trip(index: int) -> None:
    decoded = barcode.decode(_frame(index=index))
    assert decoded is not None
    assert decoded.index == index
    assert decoded.rotation == 0


@pytest.mark.parametrize("k", [1, 2, 3])
def test_rotations(k: int) -> None:
    f = np.rot90(_frame(index=777), k=k)
    decoded = barcode.decode(np.ascontiguousarray(f))
    assert decoded is not None
    assert decoded.index == 777


def test_survives_scaling_noise_and_contrast_compression() -> None:
    rng = np.random.default_rng(1)
    f = _frame(index=4242).astype(np.float64)
    f = f * 0.7 + 20 + rng.normal(0, 8, f.shape)  # tone-map-like compression plus noise
    f = np.clip(f, 0, 255).astype(np.uint8)
    big = f.repeat(3, axis=0).repeat(3, axis=1)
    decoded = barcode.decode(big)
    assert decoded is not None
    assert decoded.index == 4242


def test_pillarbox_rect() -> None:
    content = np.ascontiguousarray(np.rot90(_frame(180, 320, 99)))  # portrait picture
    canvas = np.zeros((360, 640, 3), dtype=np.uint8)
    x = (640 - content.shape[1]) // 2
    canvas[:, x : x + content.shape[1]] = content[:360] if content.shape[0] >= 360 else 0
    canvas[: content.shape[0], x : x + content.shape[1]] = content
    decoded = barcode.decode(canvas, rect=(x, 0, content.shape[1], content.shape[0]))
    assert decoded is not None
    assert decoded.index == 99


def test_plain_picture_is_not_decoded() -> None:
    f = np.full((180, 320, 3), 128, dtype=np.uint8)
    assert barcode.decode(f) is None


def test_out_of_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        barcode.draw(np.zeros((10, 10, 3), np.uint8), barcode.MAX_INDEX + 1)
