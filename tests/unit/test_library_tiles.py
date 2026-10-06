"""Library tiles and groups for S10: captions, speech, similar, totals (ADR 0044)."""

from __future__ import annotations

from pathlib import Path

from mosaic.library import browse
from mosaic.library.context import Day, TripContext, save
from mosaic.storage import provenance
from mosaic.storage.models_project import Mosaic, Segment, SimilarityGroup, VisualObservation
from tests.unit.test_decisions import _project


def _observe(s, segment_id: int, asset_id: int, prov: int, data: dict) -> None:  # type: ignore[no-untyped-def]
    sheet = Mosaic(
        asset_id=asset_id,
        index=segment_id,
        image_key=f"k{segment_id}",
        cols=4,
        rows=4,
        tile_width=1,
        tile_height=1,
        provenance_id=prov,
    )
    s.add(sheet)
    s.flush()
    s.add(
        VisualObservation(segment_id=segment_id, mosaic_id=sheet.id, data=data, provenance_id=prov)
    )


def test_tiles_groups_and_filters(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        base = {"shot_type": "wide", "interest": "medium"}
        _observe(s, ids["a_segs"][0], ids["a"], prov, {**base, "description": "A dull start"})
        _observe(
            s,
            ids["a_segs"][1],
            ids["a"],
            prov,
            {**base, "interest": "high", "description": "Falls revealed"},
        )
        _observe(
            s,
            ids["b_segs"][0],
            ids["b"],
            prov,
            {**base, "shot_type": "close_up", "description": "A toucan"},
        )
        group = SimilarityGroup(method="embedding", size=2, provenance_id=prov)
        s.add(group)
        s.flush()
        for sid in (ids["a_segs"][2], ids["b_segs"][2]):
            seg = s.get(Segment, sid)
            assert seg is not None
            seg.similarity_group_id = group.id
        seg = s.get(Segment, ids["b_segs"][1])
        assert seg is not None
        seg.has_speech = True
        save(s, TripContext(days=[Day(date="2026-07-15", place="Arenal")]), "user")
    with project.db.session() as s:
        items = {i["asset_id"]: i for i in browse.page(s, "day", None, 50).items}
        a, b = items[ids["a"]], items[ids["b"]]
        assert a["caption"] == "Falls revealed", "the most interesting moment speaks for the clip"
        assert (b["caption"], b["shot_type"], b["has_speech"]) == ("A toucan", "close_up", True)
        assert (a["similar_count"], b["similar_count"], a["has_speech"]) == (1, 1, False)
        assert a["offline"] is False
        assert a["camera"] == {"label": "Generic", "kind": "camera"}
        f = browse.Filters(show_rejected=True)
        days = browse.groups(s, "day", f)
        assert days[0] == {
            "key": "2026-07-15",
            "label": "Day 1 · 2026-07-15",
            "day": 1,
            "date": "2026-07-15",
            "place": "Arenal",
            "count": 2,
            "clips": 2,
            "photos": 0,
            "footage_seconds": 24,
        }
        sim = browse.groups(s, "similar", f)
        assert [(g["label"], g["count"]) for g in sim] == [
            ("Similar 1", 2),
            ("No similar clips", 1),
        ]
        page = browse.page(s, "similar", None, 50, f)
        assert [i["group"] for i in page.items][:2] == [str(group.id)] * 2
        assert page.items[-1]["group"] == "none"
        first = browse.page(s, "similar", None, 1, f)
        rest = browse.page(s, "similar", first.next_cursor, 50, f)
        assert len(first.items) + len(rest.items) == 3, "keyset paging by similar group"
        speech = browse.page(s, "day", None, 50, browse.Filters(has_speech=True)).items
        assert [i["asset_id"] for i in speech] == [ids["b"]]
        silent = browse.page(s, "day", None, 50, browse.Filters(has_speech=False)).items
        assert [i["asset_id"] for i in silent] == [ids["a"]]
        close = browse.page(s, "day", None, 50, browse.Filters(shot_type="close_up")).items
        assert [i["asset_id"] for i in close] == [ids["b"]]
    project.close()


def test_offline_files_and_camera_kinds(tmp_path: Path) -> None:
    from sqlalchemy import update

    from mosaic.storage.models_project import Asset, MediaFile

    project, ids = _project(tmp_path)
    when = "2026-07-15T09:00:00+00:00"
    with project.write() as s:
        for name, status in (("a", "offline"), ("b", "missing")):
            s.add(
                MediaFile(
                    rel_path=f"{name}.mp4",
                    size=1,
                    mtime_ns=0,
                    fingerprint="",
                    media_type="video",
                    status=status,
                    asset_id=ids[name],
                    created_at=when,
                )
            )
        s.execute(update(Asset).where(Asset.id == ids["b"]).values(profile="dji"))
        s.execute(update(Asset).where(Asset.id == ids["c"]).values(camera_model="HERO12 Black"))
    with project.db.session() as s:
        items = {
            i["asset_id"]: i
            for i in browse.page(s, "day", None, 50, browse.Filters(show_rejected=True)).items
        }
        cameras = {
            g["key"]: g["label"]
            for g in browse.groups(s, "camera", browse.Filters(show_rejected=True))
        }
    assert items[ids["a"]]["offline"], "cloud-only"
    assert items[ids["b"]]["offline"], "unplugged"
    assert not items[ids["c"]]["offline"]
    assert items[ids["b"]]["camera"]["kind"] == "drone"
    assert items[ids["c"]]["camera"]["label"] == "HERO12 Black"
    assert cameras == {"0": "Unknown camera"}, "no devices in this fixture: one camera group"
    project.close()


def test_one_camera_badge_rule_for_library_and_search() -> None:
    from mosaic.storage.models_project import Asset

    still = Asset(kind="photo", profile="generic", camera_model=None, device_id=None)
    clip = Asset(kind="video", profile="gopro", camera_model="HERO12 Black", device_id=3)
    assert browse.camera_json(still, {}) == {"label": "Generic", "kind": "photo"}
    assert browse.camera_json(clip, {3: "Leo's GoPro"}) == {
        "label": "Leo's GoPro",
        "kind": "actioncam",
    }
    assert browse.camera_json(clip, {3: None})["label"] == "HERO12 Black"
