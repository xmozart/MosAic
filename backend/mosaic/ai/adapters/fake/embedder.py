"""Offline stand-in for the image/text embedder (tests and the scale run, ADR 0031).

Content-based and cheap: a picture's vector is its 4×4 colour layout, so similar frames
are close and identical frames are equal. Text maps to a hash vector. Never a default.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from PIL import Image

GRID = 4
DIM = GRID * GRID * 3


class FakeEmbedder:
    provider = "fake"

    def __init__(self, model: str = "fake") -> None:
        self.model = f"fake-{model}"
        self.dim = DIM

    @staticmethod
    def _norm(v: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        n = np.linalg.norm(v, axis=1, keepdims=True)
        out: npt.NDArray[np.float32] = (v / np.maximum(n, 1e-9)).astype(np.float32)
        return out

    def embed(self, images: Sequence[Image.Image]) -> npt.NDArray[np.float32]:
        rows = [
            np.asarray(
                img.convert("RGB").resize((GRID, GRID), Image.Resampling.BOX), np.float32
            ).reshape(-1)
            - 127.5
            for img in images
        ]
        return self._norm(np.stack(rows) if rows else np.zeros((0, DIM), np.float32))

    def embed_text(self, texts: Sequence[str], local_only: bool = False) -> npt.NDArray[np.float32]:
        rows = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.lower().encode()).digest()[:8], "little")
            rows.append(np.random.default_rng(seed).standard_normal(DIM).astype(np.float32))
        return self._norm(np.stack(rows) if rows else np.zeros((0, DIM), np.float32))
