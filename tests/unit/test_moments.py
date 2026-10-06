"""Bursts and photo + video moments (M1 step 9b, ADR 0026): pure grouping rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from mosaic.library.moments import (
    BURST_MAX_DISTANCE,
    PhotoItem,
    VideoItem,
    best_of,
    bursts,
    merge_captures,
    moments,
)

T0 = datetime(2025, 3, 1, 10, 0, tzinfo=UTC)


def _vec(seed: int, jitter: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=64)
    if jitter:
        v = v + jitter * np.random.default_rng(seed + 1000).normal(size=64)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _photo(
    sid: int,
    dt: float,
    vec: np.ndarray,
    *,
    quality: float = 0.0,
    rejected: bool = False,
    device: tuple[str | None, str | None] = ("Apple", "iPhone"),
    naive: bool = False,
) -> PhotoItem:
    t = T0 + timedelta(seconds=dt)
    return PhotoItem(
        sid, sid, t.replace(tzinfo=None) if naive else t, device, vec, quality, rejected
    )


def test_bursts_need_close_times_and_looks_and_one_camera() -> None:
    v = _vec(1)
    photos = [
        _photo(1, 0.0, v),
        _photo(2, 0.4, _vec(1, 0.01)),
        _photo(3, 0.9, _vec(1, 0.01)),
        _photo(4, 5.0, v),  # too late
        _photo(5, 5.3, _vec(2)),  # different picture
        _photo(6, 0.2, v, device=("NIKON", "Z5")),  # another camera
    ]
    groups = bursts(photos)
    assert [[p.segment_id for p in g] for g in groups] == [[1, 2, 3]]


def test_best_frame_skips_rejected_photos() -> None:
    v = _vec(1)
    members = [
        _photo(1, 0.0, v, quality=0.2),
        _photo(2, 0.3, v, quality=0.9, rejected=True),
        _photo(3, 0.6, v, quality=0.5),
    ]
    assert best_of(members) == 3
    assert best_of([_photo(9, 0, v, rejected=True)]) == 9


def test_naive_and_aware_times_never_mix() -> None:
    v = _vec(1)
    assert bursts([_photo(1, 0.0, v), _photo(2, 0.3, v, naive=True)]) == []
    video = VideoItem(10, T0, T0 + timedelta(seconds=20), v)
    assert moments(_photo(1, 5.0, v, naive=True), [video]) == []


def test_moments_need_time_overlap_and_similar_looks() -> None:
    v = _vec(3)
    photo = _photo(1, 30.0, v)
    near = VideoItem(10, T0 + timedelta(seconds=25), T0 + timedelta(seconds=35), _vec(3, 0.01))
    window_edge = VideoItem(11, T0 + timedelta(seconds=38), T0 + timedelta(seconds=45), v)
    far = VideoItem(12, T0 + timedelta(seconds=60), T0 + timedelta(seconds=70), v)
    other = VideoItem(13, T0 + timedelta(seconds=25), T0 + timedelta(seconds=35), _vec(4))
    assert moments(photo, [near, window_edge, far, other]) == [10, 11]


@given(
    gaps=st.lists(st.floats(0.05, 3.0), min_size=1, max_size=8),
    order=st.permutations(range(9)),
)
def test_bursts_are_order_independent_and_split_at_one_second(
    gaps: list[float], order: list[int]
) -> None:
    v = _vec(5)
    times = [0.0]
    for g in gaps:
        times.append(times[-1] + g)
    photos = [_photo(i + 1, t, v) for i, t in enumerate(times)]
    shuffled = [photos[i] for i in order if i < len(photos)]
    groups = bursts(shuffled)
    expected: list[list[int]] = []
    run = [1]
    for i, g in enumerate(gaps, start=2):
        if g < 1.0:
            run.append(i)
        else:
            if len(run) >= 2:
                expected.append(run)
            run = [i]
    if len(run) >= 2:
        expected.append(run)
    assert sorted([p.segment_id for p in grp] for grp in groups) == sorted(expected)
    assert BURST_MAX_DISTANCE > 0


def test_captures_merge_when_they_share_a_clip() -> None:
    groups = merge_captures([(1, [10, 11]), (2, [11]), (3, [20])])
    assert sorted(sorted(g) for g in groups) == [[1, 2, 10, 11], [3, 20]]


def test_span_lookup_is_bounded() -> None:
    from mosaic.library.moments import SpanPool, _Span, _videos_near

    spans = [
        _Span(i, T0 + timedelta(minutes=10 * i), T0 + timedelta(minutes=10 * i, seconds=30), 1)
        for i in range(1000)
    ]
    pools = (SpanPool.of(spans), SpanPool.of([]))

    class Counting:
        def __init__(self) -> None:
            self.asked: list[int] = []

        def get(self, sp: _Span) -> list[VideoItem]:
            self.asked.append(sp.asset_id)
            return []

    cache = Counting()
    photo = _photo(1, 10 * 60 * 900 + 15.0, _vec(1))  # during recording 900
    _videos_near(photo, pools, cache)
    assert cache.asked == [900], "only the overlapping recording, never earlier ones"
    late = _photo(2, 10 * 60 * 900 + 38.0, _vec(1))  # 8 s after it ended: in the window
    cache.asked.clear()
    _videos_near(late, pools, cache)
    assert cache.asked == [900]
    gone = _photo(3, 10 * 60 * 900 + 45.0, _vec(1))  # 15 s after: outside the window
    cache.asked.clear()
    _videos_near(gone, pools, cache)
    assert cache.asked == []


def test_photo_probe_key_follows_its_version(monkeypatch: object) -> None:
    from types import SimpleNamespace

    import pytest

    from mosaic.media import inventory

    ctx = SimpleNamespace(project=SimpleNamespace(id="P"))
    a = inventory._probe_key(ctx, "fp", "IMG_0001.JPG")  # type: ignore[arg-type]
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(inventory, "PHOTO_PROBE_VERSION", "photo-probe/next")
        b = inventory._probe_key(ctx, "fp", "IMG_0001.JPG")  # type: ignore[arg-type]
    finally:
        mp.undo()
    assert a != b, "a new photo reader re-probes photos"
