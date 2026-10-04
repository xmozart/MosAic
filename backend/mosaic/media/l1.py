"""L1 image algorithms on numpy/SciPy (ADR 0008). Pure functions, no I/O.

Shot detection ports the algorithm of PySceneDetect's ``AdaptiveDetector``
(BSD-3-Clause, © Brandon Castellano): an HSV content value per frame, divided by the mean
content value of the neighbouring frames.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import fft, ndimage

U8 = npt.NDArray[np.uint8]
F64 = npt.NDArray[np.float64]

ADAPTIVE_THRESHOLD = 3.0
MIN_CONTENT_VAL = 15.0
WINDOW_WIDTH = 2


# ------------------------------------------------------------------- colour


def rgb_to_hsv(rgb: U8) -> F64:
    """HSV with OpenCV-compatible 8-bit scaling: H in [0, 180), S and V in [0, 255]."""
    x = rgb.astype(np.float64) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    v = x.max(axis=-1)
    mn = x.min(axis=-1)
    delta = v - mn
    s = np.where(v > 0, delta / np.where(v > 0, v, 1), 0.0)
    safe = np.where(delta > 0, delta, 1)
    h = np.where(v == r, (g - b) / safe, np.where(v == g, 2 + (b - r) / safe, 4 + (r - g) / safe))
    h = np.where(delta > 0, (h * 60.0) % 360.0, 0.0)
    return np.stack([h / 2.0, s * 255.0, v * 255.0], axis=-1)


def luma(rgb: U8) -> F64:
    """BT.709 luma in [0, 255] from full-range RGB."""
    x = rgb.astype(np.float64)
    out: F64 = x[..., 0] * 0.2126 + x[..., 1] * 0.7152 + x[..., 2] * 0.0722
    return out


def content_value(hsv_a: F64, hsv_b: F64) -> float:
    """Mean absolute HSV difference between consecutive frames (PySceneDetect weights 1:1:1)."""
    d = np.abs(hsv_a - hsv_b)
    return float(d[..., 0].mean() + d[..., 1].mean() + d[..., 2].mean()) / 3.0


# ------------------------------------------------------------------- shots


def adaptive_cuts(
    content: Sequence[float],
    min_scene_len: int,
    threshold: float = ADAPTIVE_THRESHOLD,
    min_content_val: float = MIN_CONTENT_VAL,
    window: int = WINDOW_WIDTH,
) -> list[int]:
    """Frame indices where a new shot starts (excluding 0).

    ``content[i]`` is the change from frame i-1 to frame i (``content[0]`` is 0).
    """
    n = len(content)
    cuts: list[int] = []
    last = 0
    for i in range(window, n - window):
        neighbours = [content[j] for j in range(i - window, i + window + 1) if j != i]
        avg = sum(neighbours) / len(neighbours)
        ratio = content[i] / avg if avg > 0 else (255.0 if content[i] >= min_content_val else 0)
        if ratio >= threshold and content[i] >= min_content_val and i - last >= min_scene_len:
            cuts.append(i)
            last = i
    return cuts


def force_split(starts: list[int], total: int, max_len: int) -> list[tuple[int, int, str]]:
    """Shots as ``(start, end, method)``; shots longer than ``max_len`` frames are split
    evenly."""
    bounds = [*starts, total]
    out: list[tuple[int, int, str]] = []
    for a, b in itertools.pairwise(bounds):
        if b <= a:
            continue
        parts = max(1, -(-(b - a) // max_len))
        step = (b - a) / parts
        for p in range(parts):
            s = a + round(p * step)
            e = a + round((p + 1) * step) if p < parts - 1 else b
            out.append((s, e, "adaptive" if p == 0 else "forced"))
    return out


# ------------------------------------------------------------------- hashes


def phash(gray: F64) -> int:
    """64-bit perceptual hash: sign of the low 8×8 DCT coefficients of a 32×32 image."""
    small = resize_mean(gray, 32, 32)
    coeffs = fft.dctn(small, norm="ortho")[:8, :8]
    flat = coeffs.flatten()[1:]
    med = float(np.median(flat))
    bits = 0
    for i, c in enumerate(coeffs.flatten()):
        if i and c > med:
            bits |= 1 << i
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def resize_mean(img: F64, w: int, h: int) -> F64:
    """Area-average resize (good enough for hashing tiny images)."""
    ih, iw = img.shape
    ys = np.linspace(0, ih, h + 1).astype(int)
    xs = np.linspace(0, iw, w + 1).astype(int)
    out = np.empty((h, w), dtype=np.float64)
    for y in range(h):
        for x in range(w):
            block = img[ys[y] : max(ys[y + 1], ys[y] + 1), xs[x] : max(xs[x + 1], xs[x] + 1)]
            out[y, x] = block.mean()
    return out


# ------------------------------------------------------------------- metrics

_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)


@dataclass(frozen=True)
class FrameMetrics:
    sharpness: float  # variance of the Laplacian (higher is sharper)
    exposure_mean: float  # mean luma, 0..255
    clip_low: float  # fraction of near-black pixels
    clip_high: float  # fraction of near-white pixels
    noise: float  # Immerkær sigma estimate
    obstruction: float  # fraction of the frame that is dark and textureless


def frame_metrics(gray: F64) -> FrameMetrics:
    h, w = gray.shape
    if h < 16 or w < 16:
        raise ValueError(f"frame too small for metrics: {w}x{h}")
    lap = ndimage.laplace(gray)
    conv = ndimage.convolve(gray, _IMMERKAER, mode="reflect")
    noise = float(np.sqrt(np.pi / 2) * np.abs(conv[1:-1, 1:-1]).sum() / (6 * (w - 2) * (h - 2)))
    # Obstruction: 16×16 blocks that are both dark and flat (a finger, a lens cap, a pocket).
    bh, bw = max(1, h // 16), max(1, w // 16)
    blocks = gray[: bh * 16, : bw * 16].reshape(16, bh, 16, bw)
    dark_flat = (blocks.mean(axis=(1, 3)) < 40) & (blocks.std(axis=(1, 3)) < 6)
    return FrameMetrics(
        sharpness=float(lap.var()),
        exposure_mean=float(gray.mean()),
        clip_low=float((gray < 8).mean()),
        clip_high=float((gray > 247).mean()),
        noise=noise,
        obstruction=float(dark_flat.mean()),
    )


# ------------------------------------------------------------------- motion


def phase_shift(a: F64, b: F64) -> tuple[float, float]:
    """Global translation (dx, dy) in pixels from frame a to frame b by phase correlation."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa = fft.fft2((a - a.mean()) * win)
    fb = fft.fft2((b - b.mean()) * win)
    cross = fa * np.conj(fb)
    cross /= np.abs(cross) + 1e-9
    corr = np.abs(fft.ifft2(cross))
    y, x = np.unravel_index(int(np.argmax(corr)), corr.shape)
    h, w = corr.shape
    dy = y if y <= h // 2 else y - h
    dx = x if x <= w // 2 else x - w
    return float(-dx), float(-dy)


def jitter(shifts: Sequence[tuple[float, float]], width: int, smooth: int) -> list[float]:
    """Per-frame shake: |shift − moving average| normalized by frame width."""
    if not shifts:
        return []
    arr = np.asarray(shifts, dtype=np.float64)
    k = max(1, smooth)
    kernel = np.ones(k) / k
    smoothed = np.stack([np.convolve(arr[:, i], kernel, mode="same") for i in range(2)], axis=1)
    resid = np.linalg.norm(arr - smoothed, axis=1) / max(width, 1)
    return [float(x) for x in resid]


def per_window(values: Sequence[float], window: int, how: str = "rms") -> list[float]:
    """Aggregate a per-frame series into consecutive windows (e.g. one per second)."""
    out: list[float] = []
    for i in range(0, len(values), max(window, 1)):
        chunk = np.asarray(values[i : i + window], dtype=np.float64)
        if how == "rms":
            out.append(float(np.sqrt((chunk**2).mean())))
        else:
            out.append(float(chunk.mean()))
    return out


def freeze_runs(content: Sequence[float], min_len: int, eps: float = 0.3) -> list[tuple[int, int]]:
    """Runs of frames with (almost) no change: frozen or duplicated frames."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, c in enumerate(content):
        if i and c < eps:
            start = i if start is None else start
        else:
            if start is not None and i - start >= min_len:
                runs.append((start, i))
            start = None
    if start is not None and len(content) - start >= min_len:
        runs.append((start, len(content)))
    return runs
