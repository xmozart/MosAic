"""Waveform peaks: chunked reduction equals one pass; exact bucket sizes (ADR 0037)."""

from __future__ import annotations

import itertools
import math
from fractions import Fraction

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from mosaic.media.waveform import (
    BUCKET_SAMPLES,
    MAX_BUCKETS,
    RATE,
    bucket_samples,
    peaks,
    peaks_stream,
)


@given(
    st.integers(min_value=0, max_value=30_000),
    st.integers(min_value=BUCKET_SAMPLES, max_value=10_000),
    st.lists(st.integers(min_value=1, max_value=9_000), max_size=12),
    st.integers(min_value=0, max_value=2**32 - 1),
)
def test_chunked_peaks_equal_one_pass(n: int, per_bucket: int, cuts: list[int], seed: int) -> None:
    samples = np.random.default_rng(seed).uniform(-1, 1, n).astype(np.float32)
    bounds = sorted({0, n, *(c % (n + 1) for c in cuts)})
    chunks = [samples[a:b] for a, b in itertools.pairwise(bounds)]
    got = peaks_stream(iter(chunks), per_bucket)
    assert got == peaks(samples, per_bucket)
    assert len(got) == math.ceil(n / per_bucket)


def test_peaks_scale_and_partial_last_bucket() -> None:
    s = np.zeros(1000, dtype=np.float32)
    s[10] = 1.0
    s[999] = -0.25  # in the partial last bucket
    p = peaks(s, 400)
    assert list(p) == [255, 0, round(math.sqrt(0.25) * 255)]


@given(st.fractions(min_value=Fraction(0), max_value=Fraction(200 * 3600)))
def test_bucket_sizes_cover_the_clip(duration: Fraction) -> None:
    b = bucket_samples(duration)
    assert b >= BUCKET_SAMPLES
    assert b * MAX_BUCKETS >= duration * RATE, "never more than MAX_BUCKETS buckets"
