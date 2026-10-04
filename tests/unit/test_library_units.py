from __future__ import annotations

import itertools
import struct
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image

from mosaic.library.embed_task import dedupe_by_embedding
from mosaic.library.embedder import preprocess
from mosaic.library.segments import (
    MAX_SEG,
    SPEECH_STRETCH,
    Candidate,
    inside,
    merge_intervals,
    split_shot,
    unsettled_run,
    usable_ranges,
)
from mosaic.library.similarity import leader_groups
from mosaic.media import gpmf
from mosaic.media.telemetry import second_ranges

TB = Fraction(1, 90000)
S = 90000  # ticks per second


def _gyro_payload(samples: list[tuple[int, int, int]], scal: int) -> bytes:
    gyro = b"".join(struct.pack(">hhh", *x) for x in samples)
    strm = gpmf.encode("SCAL", "s", 2, struct.pack(">h", scal), 1) + gpmf.encode(
        "GYRO", "s", 6, gyro, len(samples)
    )
    devc = gpmf.encode("STRM", "\x00", 1, strm, len(strm))
    return gpmf.encode("DEVC", "\x00", 1, devc, len(devc))


def test_gpmf_parses_scaled_gyro_and_skips_unknown_keys() -> None:
    payload = _gyro_payload([(100, -200, 300), (0, 0, 10)], scal=100)
    payload += gpmf.encode("DVNM", "c", 1, b"Camera", 6)  # unrelated top-level entry
    assert gpmf.gyro_samples(payload) == [(1.0, -2.0, 3.0), (0.0, 0.0, 0.1)]
    assert gpmf.gyro_samples(b"\x00" * 8) == []


def test_gyro_shake_ignores_smooth_pans_and_sees_jitter() -> None:
    pan = [(0.5, 0.0, 0.0)] * 400  # constant rotation: intentional, not shake
    jitter = [((1 if i % 2 else -1) * 1.0, 0.0, 0.0) for i in range(400)]
    assert max(gpmf.shake_per_second(pan, Fraction(2))[1:-1] or [0]) < 1e-9
    shaky = gpmf.shake_per_second(jitter, Fraction(2))
    assert len(shaky) == 2
    assert min(shaky) > 0.5


def test_merge_intervals() -> None:
    assert merge_intervals([(5, 9), (0, 3), (8, 12)]) == [(0, 3), (5, 12)]
    assert merge_intervals([(0, 3), (4, 6)], gap=1) == [(0, 6)]


def test_split_shot_respects_max_length_and_candidates() -> None:
    pieces = split_shot(0, 50 * S, TB, [], [])
    assert pieces[0][0] == 0
    assert pieces[-1][1] == 50 * S
    assert all(b - a <= MAX_SEG * S for a, b in pieces)
    # A strong visual change inside the window is used as the cut.
    pieces = split_shot(0, 30 * S, TB, [Candidate(12 * S, 0.4), Candidate(8 * S, 0.2)], [])
    assert pieces[0] == (0, 12 * S)


def test_split_shot_never_cuts_inside_a_sentence() -> None:
    sentence = [(14 * S, 26 * S)]
    pieces = split_shot(0, 40 * S, TB, [Candidate(18 * S, 0.9)], sentence)
    for a, b in pieces:
        for x, y in sentence:
            assert not (a < x < b < y), pieces
            assert not (x < a < y < b), pieces
    assert pieces[0][1] in (14 * S, 26 * S)


def test_short_shot_is_one_segment() -> None:
    assert split_shot(0, 5 * S, TB, [Candidate(2 * S, 0.9)], []) == [(0, 5 * S)]


def test_unsettled_run_has_a_floor() -> None:
    assert unsettled_run([0.02, 0.02, 0.0, 0.0], 0.0, 0.004, from_end=False) == 2
    assert unsettled_run([0.0, 0.0, 0.03], 0.0, 0.004, from_end=True) == 1
    assert unsettled_run([0.003, 0.0], 0.0, 0.004, from_end=False) == 0
    assert unsettled_run([0.03, 0.02], 0.02, 0.004, from_end=False) == 0  # shaky throughout


def test_leader_groups_do_not_chain() -> None:
    # 1~2 and 2~3 are close, 1 and 3 are not: single linkage would merge all three.
    dist = {(1, 2): 0.03, (2, 3): 0.03, (1, 3): 0.2, (4, 5): 0.01}

    def neighbours(i: int) -> list[tuple[float, int]]:
        return [(d, b if a == i else a) for (a, b), d in dist.items() if i in (a, b)]

    groups = leader_groups([1, 2, 3, 4, 5], neighbours, 0.06)
    assert sorted(groups) == [(1, [1, 2]), (4, [4, 5])]


def test_siglip_preprocess() -> None:
    img = Image.fromarray(np.full((360, 640, 3), 255, dtype=np.uint8))
    batch = preprocess([img, img])
    assert batch.shape == (2, 3, 224, 224)
    assert batch.dtype == np.float32
    assert float(batch.max()) == pytest.approx(1.0)


@given(
    st.integers(min_value=0, max_value=10**6),
    st.integers(min_value=1, max_value=200 * S),
    st.lists(st.tuples(st.integers(0, 200 * S), st.floats(0.01, 1.0)), max_size=12),
    st.lists(st.tuples(st.integers(0, 200 * S), st.integers(S // 2, 15 * S)), max_size=5),
)
def test_split_shot_properties(
    a: int, length: int, cands: list[tuple[int, float]], sentences: list[tuple[int, int]]
) -> None:
    b = a + length
    speech = merge_intervals([(a + x, a + x + d) for x, d in sentences])
    candidates = [Candidate(a + t, sc) for t, sc in cands]
    pieces = split_shot(a, b, TB, candidates, speech)
    assert pieces[0][0] == a
    assert pieces[-1][1] == b
    for (_, e), (s2, _) in itertools.pairwise(pieces):
        assert e == s2  # tiles [a, b) without gaps or overlaps
    limit = (MAX_SEG + SPEECH_STRETCH) * S
    for x, y in pieces[:-1]:
        assert a < y < b
        assert y - x <= limit
        hit = inside(y, speech)
        # A cut lands inside a sentence only when the sentence is too long to keep whole.
        if hit is not None:
            assert hit[1] - hit[0] > limit or hit[1] > x + limit


@given(st.lists(st.tuples(st.integers(0, 30), st.integers(0, 30), st.floats(0, 0.2)), max_size=60))
def test_leader_groups_properties(edges: list[tuple[int, int, float]]) -> None:
    dist: dict[tuple[int, int], float] = {}
    for x, y, d in edges:
        if x != y:
            dist[(min(x, y), max(x, y))] = d

    def neighbours(i: int) -> list[tuple[float, int]]:
        return [(d, q if p == i else p) for (p, q), d in dist.items() if i in (p, q)]

    groups = leader_groups(list(range(31)), neighbours, 0.06)
    seeds = {seed for seed, _ in groups}
    seen: set[int] = set()
    for seed, members in groups:
        assert seed in members
        assert not (set(members) - {seed}) & seeds  # no member seeds another group
        assert not set(members) & seen  # groups are disjoint
        seen |= set(members)
        for m in members:
            if m != seed:
                assert dist[(min(m, seed), max(m, seed))] <= 0.06


def test_embedding_dedupe_keeps_scene_and_ignores_phash_drops() -> None:
    v = {i: np.array([1.0, 0.0], dtype=np.float32) for i in range(1, 6)}
    v[4] = np.array([0.0, 1.0], dtype=np.float32)
    samples = [
        (1, 10, "scene", None),
        (2, 10, "interval", None),
        (3, 10, "interval", "phash"),
        (4, 10, "interval", None),
        (5, 11, "scene", None),
    ]
    assert dedupe_by_embedding(samples, v, 0.97) == {2: 1}
    # An earlier embedding drop is recomputed, not trusted.
    again = [(1, 10, "scene", None), (2, 10, "interval", "embedding")]
    assert dedupe_by_embedding(again, v, 0.97) == {2: 1}
    assert dedupe_by_embedding(again, v, 1.01) == {}


def test_telemetry_second_ranges_with_offset_and_fractional_duration() -> None:
    rows = second_ranges(start=10 * S, duration=S * 5 // 2, tb=TB, values=[0.1, 0.2, 0.3])
    assert rows == [(10 * S, 11 * S, 0.1), (11 * S, 12 * S, 0.2), (12 * S, 12 * S + S // 2, 0.3)]
    assert second_ranges(0, S, TB, [0.1, 0.2]) == [(0, S, 0.1)]  # nothing past the end


def test_usable_trim_carries_across_a_short_first_piece() -> None:
    pieces = [(0, S), (S, 5 * S), (5 * S, 10 * S)]
    usable = usable_ranges(pieces, trim_head=2 * S, trim_tail=9 * S)
    assert usable == [(S, S), (2 * S, 5 * S), (5 * S, 9 * S)]
