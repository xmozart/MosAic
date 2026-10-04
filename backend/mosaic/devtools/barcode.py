"""Encode-robust frame-index barcode for synthetic media (ADR 0002 item E).

The barcode occupies the top ``BAND_FRACTION`` of the coded frame as a grid of
``ROWS × COLS`` large cells, so it survives scaling, chroma subsampling, lossy
encoding, tone mapping and pillarboxing. Four corner cells are a sync pattern
that also identifies orientation, so frames rotated by the display matrix can be
decoded by trying the four rotations.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

ROWS = 2
COLS = 12
BAND_FRACTION = 0.34
WHITE = 232
BLACK = 24

_SYNC = {(0, 0): 1, (0, COLS - 1): 0, (1, 0): 0, (1, COLS - 1): 1}
_DATA_CELLS = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in _SYNC]
DATA_BITS = len(_DATA_CELLS) - 2  # last two cells are parity
MAX_INDEX = (1 << DATA_BITS) - 1

Frame = npt.NDArray[np.uint8]


def _bits_for(index: int) -> dict[tuple[int, int], int]:
    if not 0 <= index <= MAX_INDEX:
        raise ValueError(f"frame index {index} out of range 0..{MAX_INDEX}")
    data = [(index >> i) & 1 for i in range(DATA_BITS)]
    parity = [sum(data[0::2]) & 1, sum(data[1::2]) & 1]
    cells = dict(_SYNC)
    for cell, bit in zip(_DATA_CELLS, data + parity, strict=True):
        cells[cell] = bit
    return cells


def band_height(height: int) -> int:
    return max(ROWS, int(height * BAND_FRACTION))


def draw(frame: Frame, index: int) -> None:
    """Draw the barcode for ``index`` into the top band of an RGB frame in place."""
    h, w = frame.shape[:2]
    bh = band_height(h)
    for (r, c), bit in _bits_for(index).items():
        y0, y1 = r * bh // ROWS, (r + 1) * bh // ROWS
        x0, x1 = c * w // COLS, (c + 1) * w // COLS
        frame[y0:y1, x0:x1] = WHITE if bit else BLACK


@dataclass(frozen=True)
class Decoded:
    index: int
    rotation: int  # quarter turns counter-clockwise applied to undo the display rotation


def _cell_means(region: npt.NDArray[np.float64]) -> dict[tuple[int, int], float]:
    h, w = region.shape
    bh = band_height(h)
    means: dict[tuple[int, int], float] = {}
    for r in range(ROWS):
        for c in range(COLS):
            y0, y1 = r * bh // ROWS, (r + 1) * bh // ROWS
            x0, x1 = c * w // COLS, (c + 1) * w // COLS
            cy0, cy1 = y0 + (y1 - y0) // 4, y1 - (y1 - y0) // 4
            cx0, cx1 = x0 + (x1 - x0) // 4, x1 - (x1 - x0) // 4
            means[(r, c)] = float(region[cy0 : max(cy1, cy0 + 1), cx0 : max(cx1, cx0 + 1)].mean())
    return means


def _decode_upright(luma: npt.NDArray[np.float64]) -> int | None:
    means = _cell_means(luma)
    white = (means[(0, 0)] + means[(1, COLS - 1)]) / 2
    black = (means[(0, COLS - 1)] + means[(1, 0)]) / 2
    if white - black < 40:
        return None
    span = white - black
    bits: list[int] = []
    for cell, value in means.items():
        u = (value - black) / span
        if 0.3 < u < 0.7:
            return None  # not a barcode cell: mid-tone picture content
        if cell in _SYNC and (u > 0.5) != bool(_SYNC[cell]):
            return None
    bits = [1 if (means[cell] - black) / span > 0.5 else 0 for cell in _DATA_CELLS]
    data, parity = bits[:DATA_BITS], bits[DATA_BITS:]
    if parity != [sum(data[0::2]) & 1, sum(data[1::2]) & 1]:
        return None
    return sum(bit << i for i, bit in enumerate(data))


def decode(frame: Frame, rect: tuple[int, int, int, int] | None = None) -> Decoded | None:
    """Decode the frame index from an RGB (or gray) frame.

    ``rect`` is ``(x, y, w, h)`` of the picture area inside the frame (for example the
    pillarboxed content); default is the whole frame. Rotations are tried in order.
    """
    arr = frame.astype(np.float64)
    luma = arr if arr.ndim == 2 else arr[..., :3] @ np.array([0.299, 0.587, 0.114])
    if rect is not None:
        x, y, w, h = rect
        luma = luma[y : y + h, x : x + w]
    for quarter_turns in range(4):
        candidate = np.rot90(luma, k=quarter_turns)
        index = _decode_upright(candidate)
        if index is not None:
            return Decoded(index=index, rotation=quarter_turns)
    return None
