"""Search helpers (M1 step 11, ADR 0029)."""

from __future__ import annotations

from mosaic.storage.sqlite_fts import match_query


def test_match_query_quotes_words_and_drops_syntax() -> None:
    assert (
        match_query("Fighter jets, over the BAY!")
        == '"fighter"* OR "jets"* OR "over"* OR "the"* OR "bay"*'
    )
    assert match_query('"NEAR(a b') == '"near"*'
    assert match_query("* ( ) -") is None
    assert match_query("x") is None, "single letters are noise"
    assert match_query("jet jet") == '"jet"*'


def test_fuse_rewards_agreement() -> None:
    from mosaic.library.search import RRF_K, fuse

    scores = fuse([[1, 2, 3], [3, 4]])
    assert scores[3] > scores[1] > scores[2], "found by both rankings beats either alone"
    assert scores[1] == 1 / (RRF_K + 1)
    assert fuse([]) == {}
