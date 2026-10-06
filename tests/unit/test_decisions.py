"""The owner's clip decisions: precedence, editing, library filters (ADR 0042)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select

from mosaic.library import browse, decisions
from mosaic.storage import provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, Disposition, Segment, Shot
from mosaic.storage.projects import Project, init_project

T = "2026-07-15T09:00:00+00:00"
SEC = 90000  # ticks per second at 1/90000


def _project(tmp_path: Path) -> tuple[Project, dict[str, Any]]:
    """Three clips of three 4 s segments each; the analysis says USE, MAYBE, REJECT per
    clip; clip ``c`` is a photo-free video with a better middle segment."""
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    ids: dict[str, Any] = {"control": control}
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        for name, ai, day in (("a", "USE", "15"), ("b", "MAYBE", "15"), ("c", "REJECT", "16")):
            a = Asset(
                kind="video",
                status="ok",
                profile="generic",
                group_key=name,
                capture_time=f"2026-07-{day}T09:00:00+00:00",
                tb="1/90000",
                duration_ticks=12 * SEC,
                provenance_id=prov,
                created_at=T,
            )
            s.add(a)
            s.flush()
            shot = Shot(
                asset_id=a.id,
                index=0,
                start_ticks=0,
                end_ticks=12 * SEC,
                method="adaptive",
                provenance_id=prov,
            )
            s.add(shot)
            s.flush()
            segs = []
            for i in range(3):
                g = Segment(
                    asset_id=a.id,
                    shot_id=shot.id,
                    index=i,
                    start_ticks=i * 4 * SEC,
                    end_ticks=(i + 1) * 4 * SEC,
                    usable_start_ticks=i * 4 * SEC,
                    usable_end_ticks=(i + 1) * 4 * SEC,
                    quality=0.9 if i == 1 else 0.5,
                    provenance_id=prov,
                )
                s.add(g)
                s.flush()
                segs.append(g.id)
                s.add(
                    Disposition(
                        asset_id=a.id,
                        segment_id=g.id,
                        anchor_start_ticks=g.start_ticks,
                        anchor_end_ticks=g.end_ticks,
                        source="ai",
                        status=ai,
                        updated_at=T,
                    )
                )
            ids[name] = a.id
            ids[f"{name}_segs"] = segs
    return project, ids


def test_precedence_segment_user_then_clip_then_ai(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    with project.write() as s:
        decisions.apply(s, [ids["c"]], {"disposition": "USE"})
        s.add(
            Disposition(
                asset_id=ids["c"],
                segment_id=ids["c_segs"][2],
                anchor_start_ticks=8 * SEC,
                anchor_end_ticks=12 * SEC,
                source="user",
                status="REJECT",
                updated_at=T,
            )
        )
    with project.db.session() as s:
        asset = s.get(Asset, ids["c"])
        assert asset is not None
        segs = [s.get(Segment, i) for i in ids["c_segs"]]
        got = decisions.for_segments(s, asset, [g for g in segs if g])
    first, middle, last = (got[i] for i in ids["c_segs"])
    assert (first.status, first.source, first.forced) == ("USE", "clip", False)
    assert (middle.status, middle.source, middle.forced) == ("USE", "clip", True), "best forced"
    assert (last.status, last.source) == ("REJECT", "user"), "the segment's own decision wins"
    project.close()


def test_editing_honours_clip_decisions(tmp_path: Path) -> None:
    from mosaic.editing.retrieval import retrieve

    project, ids = _project(tmp_path)
    with project.write() as s:
        decisions.apply(s, [ids["a"]], {"include": "never"})
        decisions.apply(s, [ids["c"]], {"include": "always"})
    with project.db.session() as s:
        cands, _counts = retrieve(s, Fraction(1), Fraction(30))
        rejected = decisions.user_rejected(s)
    by_asset: dict[int, list[Any]] = {}
    for c in cands:
        by_asset.setdefault(c.asset_id, []).append(c)
    assert ids["a"] not in by_asset, "never include keeps the clip out of every edit"
    assert set(ids["a_segs"]) <= rejected
    kept = by_asset[ids["c"]]
    assert {c.segment_id for c in kept} == set(ids["c_segs"]), "always overrides AI REJECT"
    assert [c.segment_id for c in kept if c.user_use] == [ids["c_segs"][1]], "best only forced"
    assert not set(ids["c_segs"]) & rejected
    project.close()


def test_apply_resets_tags_and_removes_empty_rows(tmp_path: Path) -> None:
    from mosaic.storage.models_project import ClipDecision

    project, ids = _project(tmp_path)
    a = ids["a"]
    with project.write() as s:
        assert decisions.apply(s, [a], {"stars": 4, "tags": ["toucan", "bird"]}) == {
            a: ["stars", "tags"]
        }
        assert decisions.apply(s, [a], {"stars": 4}) == {}, "no change, nothing reported"
        decisions.apply(s, [a], {"add_tags": ["day 2"], "remove_tags": ["bird"]})
    with project.db.session() as s:
        assert decisions.tags(s, [a]) == {a: ["day 2", "toucan"]}
    with project.write() as s:
        decisions.apply(s, [a], {"stars": None})
    with project.db.session() as s:
        assert s.get(ClipDecision, a) is None, "an all-empty decision row is removed"
    with project.write() as s, pytest.raises(LookupError):
        decisions.apply(s, [a, 999], {"stars": 1})
    project.close()


def test_library_filters_and_tile_status(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    with project.write() as s:
        decisions.apply(s, [ids["b"]], {"disposition": "USE", "stars": 5, "tags": ["zip"]})
    with project.db.session() as s:
        page = browse.page(s, "day", None, 50)
        shown = {i["asset_id"]: (i["status_shown"], i["decided_by"]) for i in page.items}
        assert shown == {ids["a"]: ("USE", "ai"), ids["b"]: ("USE", "user")}, "rejected hidden"
        assert browse.rejected_hidden(s, browse.Filters()) == 1
        everything = browse.page(s, "day", None, 50, browse.Filters(show_rejected=True))
        assert len(everything.items) == 3
        assert everything.groups is not None
        assert [g["label"] for g in everything.groups] == [
            "Day 1 · 2026-07-15",
            "Day 2 · 2026-07-16",
        ]
        only_rejected = browse.page(s, "day", None, 50, browse.Filters(status="REJECT"))
        assert [i["asset_id"] for i in only_rejected.items] == [ids["c"]]
        assert only_rejected.groups is not None
        assert [(g["key"], g["day"], g["count"]) for g in only_rejected.groups] == [
            ("2026-07-16", 2, 1)
        ], "a filter keeps the trip's day numbers"
        starred = browse.page(s, "day", None, 50, browse.Filters(min_stars=4))
        assert [i["asset_id"] for i in starred.items] == [ids["b"]]
        assert starred.items[0]["decision"]["tags"] == ["zip"]
        assert (
            browse.page(s, "day", None, 50, browse.Filters(tag="zip")).items[0]["asset_id"]
            == ids["b"]
        )
        assert browse.page(s, "day", None, 50, browse.Filters(kind="photo")).items == []
        assert len(browse.page(s, "day", None, 50, browse.Filters(day="2026-07-15")).items) == 2
        # Paging stays keyset-correct under a filter.
        first = browse.page(s, "day", None, 1, browse.Filters(show_rejected=True))
        second = browse.page(s, "day", first.next_cursor, 1, browse.Filters(show_rejected=True))
        assert first.items[0]["asset_id"] != second.items[0]["asset_id"]
    project.close()


def _user_row(s: Any, asset_id: int, segment_id: int, start: int, status: str) -> None:
    s.add(
        Disposition(
            asset_id=asset_id,
            segment_id=segment_id,
            anchor_start_ticks=start * 4 * SEC,
            anchor_end_ticks=(start + 1) * 4 * SEC,
            source="user",
            status=status,
            updated_at=T,
        )
    )


def test_never_beats_an_older_segment_use(tmp_path: Path) -> None:
    from mosaic.editing.retrieval import retrieve

    project, ids = _project(tmp_path)
    with project.write() as s:
        _user_row(s, ids["a"], ids["a_segs"][0], 0, "USE")
        decisions.apply(s, [ids["a"]], {"include": "never"})
    with project.db.session() as s:
        asset = s.get(Asset, ids["a"])
        assert asset is not None
        got = decisions.for_segments(
            s, asset, [g for g in (s.get(Segment, i) for i in ids["a_segs"]) if g]
        )
        assert {d.status for d in got.values()} == {"REJECT"}
        assert not any(d.forced for d in got.values())
        cands, _ = retrieve(s, Fraction(1), Fraction(30))
        assert ids["a"] not in {c.asset_id for c in cands}
        assert set(ids["a_segs"]) <= decisions.user_rejected(s)
        tile = browse.page(s, "day", None, 50, browse.Filters(show_rejected=True)).items
        a = next(i for i in tile if i["asset_id"] == ids["a"])
        assert (a["status_shown"], a["decided_by"]) == ("REJECT", "user")
    project.close()


def test_clip_reject_keeps_a_segment_the_owner_kept(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    with project.write() as s:
        _user_row(s, ids["a"], ids["a_segs"][1], 1, "USE")
        decisions.apply(s, [ids["a"]], {"disposition": "REJECT"})
    with project.db.session() as s:
        rejected = decisions.user_rejected(s)
    assert ids["a_segs"][1] not in rejected, "a segment decision wins over the clip's REJECT"
    assert {ids["a_segs"][0], ids["a_segs"][2]} <= rejected
    project.close()


def test_resetting_an_undecided_clip_is_a_no_op(tmp_path: Path) -> None:
    from mosaic.storage.models_project import ClipDecision

    project, ids = _project(tmp_path)
    with project.write() as s:
        assert decisions.apply(s, [ids["a"], ids["b"]], {"stars": None, "include": None}) == {}
    with project.db.session() as s:
        assert s.scalar(select(func.count()).select_from(ClipDecision)) == 0
    project.close()


def test_decided_by_follows_the_winning_status(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    with project.write() as s:
        _user_row(s, ids["a"], ids["a_segs"][0], 0, "REJECT")  # the AI's USE still wins
        decisions.apply(s, [ids["b"]], {"disposition": "MAYBE"})  # a clip rule: the owner's
    with project.db.session() as s:
        items = browse.page(s, "day", None, 50).items
    shown = {i["asset_id"]: (i["status_shown"], i["decided_by"]) for i in items}
    assert shown[ids["a"]] == ("USE", "ai")
    assert shown[ids["b"]] == ("MAYBE", "user")
    project.close()


def test_a_decision_changes_the_edit_inputs(tmp_path: Path) -> None:
    from mosaic.editing.generate import _inputs_digest
    from mosaic.editing.retrieval import retrieve

    project, ids = _project(tmp_path)

    def digest() -> str:
        with project.db.session() as s:
            cands, _ = retrieve(s, Fraction(1), Fraction(30))
            return _inputs_digest(s, cands)

    before = digest()
    with project.write() as s:
        decisions.apply(s, [ids["b"]], {"disposition": "USE"})
    after = digest()
    assert before != after, "edits are re-made after a decision (invariant 9)"
    with project.write() as s:
        decisions.apply(s, [ids["b"]], {"stars": 5, "tags": ["x"]})
    assert digest() == after, "stars and tags do not change the edit"
    project.close()


def test_camera_include_and_kind_filters(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    with project.write() as s:
        decisions.apply(s, [ids["b"]], {"include": "always"})
    with project.db.session() as s:
        always = browse.page(s, "day", None, 50, browse.Filters(include="always")).items
        assert [i["asset_id"] for i in always] == [ids["b"]]
        assert len(browse.page(s, "day", None, 50, browse.Filters(kind="video")).items) == 2
        assert len(browse.page(s, "day", None, 50, browse.Filters(camera=0)).items) == 2
        assert browse.page(s, "day", None, 50, browse.Filters(camera=7)).items == []
    project.close()


STATUSES = ("USE", "MAYBE", "REJECT")


@given(
    ai=st.lists(st.sampled_from(STATUSES), min_size=1, max_size=3),
    user=st.lists(st.sampled_from((None, *STATUSES)), min_size=3, max_size=3),
    disposition=st.sampled_from((None, *STATUSES)),
    include=st.sampled_from((None, "always", "never")),
)
@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_the_sql_tile_status_matches_for_segments(
    tmp_path_factory: pytest.TempPathFactory,
    ai: list[str],
    user: list[str | None],
    disposition: str | None,
    include: str | None,
) -> None:
    """The library's SQL status is the best of ``for_segments``, the owner's when tied."""
    from sqlalchemy import delete

    from mosaic.storage.models_project import ClipDecision

    global _SHARED
    if _SHARED is None:
        _SHARED = _project(tmp_path_factory.mktemp("prop"))
    project, ids = _SHARED
    aid, segs = ids["c"], ids["c_segs"]
    with project.write() as s:
        s.execute(delete(Disposition).where(Disposition.asset_id == aid))
        s.execute(delete(ClipDecision).where(ClipDecision.asset_id == aid))
        for i, sid in enumerate(segs[: len(ai)]):
            s.add(
                Disposition(
                    asset_id=aid,
                    segment_id=sid,
                    anchor_start_ticks=i * 4 * SEC,
                    anchor_end_ticks=(i + 1) * 4 * SEC,
                    source="ai",
                    status=ai[i],
                    updated_at=T,
                )
            )
            if user[i]:
                _user_row(s, aid, sid, i, user[i])
        decisions.apply(s, [aid], {"disposition": disposition, "include": include})
    with project.db.session() as s:
        asset = s.get(Asset, aid)
        assert asset is not None
        analysed = [g for g in (s.get(Segment, i) for i in segs[: len(ai)]) if g]
        ref = decisions.for_segments(s, asset, analysed)
        tile = next(
            i
            for i in browse.page(s, "day", None, 50, browse.Filters(show_rejected=True)).items
            if i["asset_id"] == aid
        )
    rank = {"USE": 1, "MAYBE": 2, "REJECT": 3}
    best = min(rank[d.status] for d in ref.values() if d.status)
    owners = any(
        rank[d.status] == best and d.source in ("user", "clip") for d in ref.values() if d.status
    )
    assert tile["status_shown"] == {1: "USE", 2: "MAYBE", 3: "REJECT"}[best]
    assert tile["decided_by"] == ("user" if owners else "ai")


_SHARED: tuple[Project, dict[str, Any]] | None = None
