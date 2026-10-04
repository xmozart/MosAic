from __future__ import annotations

import numpy as np
import pytest

from mosaic.media import l1


def _noise(seed: int, h: int = 72, w: int = 128) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_hsv_matches_reference_values() -> None:
    px = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [128, 128, 128]]], dtype=np.uint8)
    hsv = l1.rgb_to_hsv(px)[0]
    assert hsv[0] == pytest.approx([0, 255, 255])
    assert hsv[1] == pytest.approx([60, 255, 255])
    assert hsv[2] == pytest.approx([120, 255, 255])
    assert hsv[3][1] == 0


def test_adaptive_cuts_find_spikes_and_respect_min_len() -> None:
    content = [0.0] + [5.0] * 49 + [60.0] + [5.0] * 49 + [60.0] + [5.0] * 3 + [60.0] + [5.0] * 20
    assert l1.adaptive_cuts(content, min_scene_len=10) == [50, 100]
    # Uniformly high change (handheld pan) is not a cut: the ratio stays ~1.
    assert l1.adaptive_cuts([40.0] * 100, min_scene_len=10) == []


def test_force_split() -> None:
    shots = l1.force_split([0, 100], 400, max_len=120)
    assert shots[0] == (0, 100, "adaptive")
    assert [s[2] for s in shots[1:]] == ["adaptive", "forced", "forced"]
    assert shots[-1][1] == 400
    assert all(b - a <= 120 for a, b, _ in shots)


def test_phash_stable_under_noise_and_distinct_across_images() -> None:
    base = l1.luma(_noise(1)).astype(np.float64)
    noisy = base + np.random.default_rng(2).normal(0, 4, base.shape)
    other = l1.luma(_noise(3)).astype(np.float64)
    from scipy import ndimage

    smooth = ndimage.gaussian_filter(base, 3)  # natural-image-like low-frequency content
    assert l1.hamming(l1.phash(smooth), l1.phash(smooth + 2)) <= 4
    assert l1.hamming(l1.phash(base), l1.phash(noisy)) <= 12
    assert l1.hamming(l1.phash(base), l1.phash(other)) > 12


def test_frame_metrics_order_sharpness_and_flag_obstruction() -> None:
    sharp = l1.luma(_noise(4)).astype(np.float64)
    from scipy import ndimage

    blurry = ndimage.gaussian_filter(sharp, 4)
    assert l1.frame_metrics(sharp).sharpness > 10 * l1.frame_metrics(blurry).sharpness
    dark = np.full((72, 128), 10.0)
    m = l1.frame_metrics(dark)
    assert m.obstruction == pytest.approx(1.0)
    assert m.clip_low == pytest.approx(0.0)
    assert l1.frame_metrics(np.full((72, 128), 2.0)).clip_low == pytest.approx(1.0)
    assert (
        l1.frame_metrics(sharp + np.random.default_rng(5).normal(0, 10, sharp.shape)).noise
        > l1.frame_metrics(blurry).noise
    )


def test_phase_shift_recovers_translation() -> None:
    img = l1.luma(_noise(6, 96, 160)).astype(np.float64)
    from scipy import ndimage

    img = ndimage.gaussian_filter(img, 1.5)
    moved = np.roll(img, shift=(3, -5), axis=(0, 1))
    dx, dy = l1.phase_shift(img, moved)
    assert (round(dx), round(dy)) == (-5, 3)


def test_jitter_separates_shake_from_smooth_pan() -> None:
    pan = [(2.0, 0.0)] * 60
    shaky = [(2.0 + (6 if i % 2 else -6), 0.0) for i in range(60)]
    assert max(l1.jitter(pan, 256, 15)[10:-10]) < 1e-9
    assert np.mean(l1.jitter(shaky, 256, 15)[10:-10]) > 0.01
    assert l1.per_window([1.0, 1.0, 3.0, 3.0], 2, "mean") == [1.0, 3.0]


def test_freeze_runs() -> None:
    content = [0.0] + [5.0] * 10 + [0.0] * 40 + [5.0] * 10
    assert l1.freeze_runs(content, 30) == [(11, 51)]
