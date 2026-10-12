"""Where a frame's subject is (ADR 0076): visual saliency by the spectral residual method
(Hou & Zhang, 2007) on a small grey copy, with numpy and SciPy.

It finds what stands out (contrast, edges, colour against the surroundings), never who:
no face or person detection and nothing biometric (CLAUDE.md "Things not to build").
Several frames of one segment are averaged, so a segment has one steady focus point.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from PIL import Image
from scipy import ndimage

MAP_WIDTH = 64  # the spectral residual works on a small copy (the method's own scale)
PEAK_POWER = 2.0  # weight the centroid towards the strongest regions


def saliency_map(img: Image.Image, width: int = MAP_WIDTH) -> np.ndarray:
    """A saliency map in [0, 1] of ``img`` at ``width`` pixels wide (aspect kept)."""
    height = max(1, round(img.height * width / max(1, img.width)))
    small = np.asarray(img.convert("L").resize((width, height), Image.Resampling.BILINEAR))
    f = np.fft.fft2(small.astype(np.float64))
    log_amp = np.log(np.abs(f) + 1e-9)
    residual = log_amp - ndimage.uniform_filter(log_amp, size=3, mode="wrap")
    sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(f)))) ** 2
    sal = ndimage.gaussian_filter(sal, sigma=width / 25)
    peak = float(sal.max())
    out: np.ndarray = np.asarray(sal / peak if peak > 0 else sal, dtype=np.float64)
    return out


def focus_point(images: Iterable[Image.Image]) -> tuple[int, int] | None:
    """The subject's position in thousandths of the frame, ``(x, y)``, from one or more
    frames of the same shot (their maps averaged); None without a frame."""
    maps = [saliency_map(img) for img in images]
    if not maps:
        return None
    h = min(m.shape[0] for m in maps)
    w = min(m.shape[1] for m in maps)
    acc = np.mean([m[:h, :w] for m in maps], axis=0) ** PEAK_POWER
    total = float(acc.sum())
    if total <= 0:
        return 500, 500
    ys, xs = np.indices(acc.shape)
    x = float((acc * (xs + 0.5)).sum()) / total / w
    y = float((acc * (ys + 0.5)).sum()) / total / h
    return round(1000 * x), round(1000 * y)
