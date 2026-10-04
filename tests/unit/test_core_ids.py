from __future__ import annotations

import pytest

from mosaic.core.ids import fmt_id, new_ulid, parse_id

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_ulid_shape_and_order() -> None:
    a = new_ulid(1_700_000_000_000)
    b = new_ulid(1_700_000_000_001)
    assert len(a) == 26
    assert set(a) <= CROCKFORD
    assert a < b
    assert new_ulid() != new_ulid()


def test_fmt_and_parse_ids() -> None:
    assert fmt_id("seg", 451) == "seg_000451"
    assert fmt_id("ast", 123) == "ast_0123"
    assert fmt_id("prov", 981) == "prov_00981"
    assert parse_id("seg", "seg_000451") == 451
    with pytest.raises(ValueError, match="not a seg id"):
        parse_id("seg", "ast_0001")
