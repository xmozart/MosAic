"""Content categories (ADR 0072): derived from what analysis knows, with no AI call."""

from __future__ import annotations

from pathlib import Path

from mosaic.editing.categories import CATEGORIES, avoided, classify, weight_bonus


def test_structured_fields_speech_rate_and_photos() -> None:
    assert classify({"shot_type": "aerial", "people": "none"}) == {"drone"}
    assert classify({"shot_type": "selfie", "people": "one"}) == {"selfies", "people"}
    assert classify({"shot_type": "wide", "people": "none"}) == {"landscapes"}
    assert classify({"shot_type": "wide", "people": "crowd"}) == {"people"}
    assert classify({"camera_motion": "vehicle"}) == {"transport"}
    assert classify({}, has_speech=True) == {"conversations"}
    assert classify({}, rate="120/1") == {"slow_motion"}
    assert classify({}, rate="30000/1001") == frozenset()
    assert classify({}, photo=True) == {"photos"}


def test_words_are_whole_words_or_marked_stems() -> None:
    assert "transport" in classify({"description": "Two cars on the road"})
    assert classify({"description": "A family carrying cards"}) == frozenset(), "car ≠ carry"
    assert classify({"description": "Kids laughing at a parrot"}) >= {"reactions", "wildlife"}
    assert classify({"subjects": ["sunset", "beach"]}) >= {"sunsets", "water"}
    assert classify({"description": "A night market, food stalls"}) >= {"night", "culture", "food"}
    # Regular plurals only: "ski" is not "skies", "car" not "cares", "run" not "runes".
    assert "action" not in classify({"description": "Orange skies over the hills"})
    assert "transport" not in classify({"description": "She cares for it"})
    assert "action" not in classify({"description": "Morning runes"})
    assert "transport" in classify({"description": "Buses and ferries"})
    assert "city" in classify({"description": "Two cities at dusk"})
    assert "water" in classify({"description": "Empty beaches"})
    assert "landscapes" not in classify({"description": "Shallow depth of field, a view"})
    assert classify({"description": None, "subjects": None}) == frozenset()


def test_the_owners_tags_count_and_names_are_productss() -> None:
    assert classify({}, tags=["Food", "slow motion", "favourite"]) == {"food", "slow_motion"}
    assert len(CATEGORIES) == 22
    assert CATEGORIES[0] == "people"
    assert CATEGORIES[-1] == "photos"


def test_weights() -> None:
    w = {"wildlife": "strong", "people": "more", "transport": "less", "selfies": "avoid"}
    assert weight_bonus({"wildlife", "people"}, w) == 2.0, "the strongest, not the sum"
    assert weight_bonus({"wildlife", "transport"}, w) == 1.0
    assert weight_bonus({"transport"}, w) == -1.0
    assert weight_bonus({"city"}, w) == 0.0
    assert avoided({"selfies", "people"}, w)
    assert not avoided({"people"}, w)


def test_library_counts_follow_the_librarys_clips(tmp_path: Path) -> None:
    from mosaic.editing.categories import library_counts
    from mosaic.storage import provenance
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_project import (
        Asset,
        ClipTag,
        Mosaic,
        Segment,
        Shot,
        VisualObservation,
    )
    from mosaic.storage.projects import init_project

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with p.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))

        def clip(kind: str, status: str, shots: list[str]) -> int:
            a = Asset(
                kind=kind,
                status=status,
                profile="generic",
                group_key=f"{kind}{status}{len(shots)}",
                created_at="x",
                provenance_id=prov,
                tb="1/1000",
                rate="30/1",
            )
            s.add(a)
            s.flush()
            sh = Shot(
                asset_id=a.id,
                index=0,
                start_ticks=0,
                end_ticks=9000,
                method="t",
                provenance_id=prov,
            )
            s.add(sh)
            s.flush()
            for i, shot_type in enumerate(shots):
                g = Segment(
                    asset_id=a.id,
                    shot_id=sh.id,
                    index=i,
                    start_ticks=i * 1000,
                    end_ticks=i * 1000 + 1000,
                    usable_start_ticks=i * 1000,
                    usable_end_ticks=i * 1000 + 1000,
                    provenance_id=prov,
                )
                s.add(g)
                s.flush()
                sheet = Mosaic(
                    asset_id=a.id,
                    index=g.id,
                    image_key=f"k{g.id}",
                    cols=1,
                    rows=1,
                    tile_width=1,
                    tile_height=1,
                    provenance_id=prov,
                )
                s.add(sheet)
                s.flush()
                s.add(
                    VisualObservation(
                        segment_id=g.id,
                        mosaic_id=sheet.id,
                        data={"shot_type": shot_type, "people": "none"},
                        provenance_id=prov,
                    )
                )
            return a.id

        drone = clip("video", "ok", ["aerial", "aerial"])  # two drone segments: one clip
        s.add(ClipTag(asset_id=drone, tag="slow motion"))
        clip("video", "ok", ["aerial"])
        clip("photo", "ok", [])
        clip("video", "unsupported", ["aerial"])  # not in the library's count
    with p.db.session() as s:
        items = library_counts(s)
    p.close()
    got = {i["category"]: i["clips"] for i in items}
    assert got["drone"] == 2
    assert got["slow_motion"] == 1
    assert got["photos"] == 1
    assert [i["category"] for i in items[:3]] == ["drone", "slow_motion", "photos"]
    zeros = [i["category"] for i in items if i["clips"] == 0]
    assert zeros == [c for c in CATEGORIES if c in zeros], "ties keep PRODUCT.md's order"
