"""Home cards (ADR 0038): the cover follows effective decisions (invariant 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaic.storage import project_cards, provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, Disposition, SampleFrame, Segment, Shot
from mosaic.storage.projects import init_project

T = "2025-06-02T09:00:00+00:00"
Clip = tuple[str, float, str | None]  # name, quality, the user's decision over an AI USE


def _cover(tmp_path: Path, clips: list[Clip]) -> tuple[list[int], dict[str, int]]:
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    frames: dict[str, int] = {}
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        for name, quality, user in clips:
            a = Asset(
                kind="video",
                status="ok",
                profile="generic",
                group_key=name,
                capture_time=T,
                tb="1/90000",
                duration_ticks=90000,
                provenance_id=prov,
                created_at=T,
            )
            s.add(a)
            s.flush()
            common: dict[str, Any] = {"asset_id": a.id, "provenance_id": prov}
            shot = Shot(index=0, start_ticks=0, end_ticks=90000, method="adaptive", **common)
            s.add(shot)
            s.flush()
            g = Segment(
                shot_id=shot.id,
                index=0,
                start_ticks=0,
                end_ticks=90000,
                usable_start_ticks=0,
                usable_end_ticks=90000,
                quality=quality,
                **common,
            )
            f = SampleFrame(
                shot_id=shot.id, ticks=10, reason="scene", phash="0" * 16, kept=True, **common
            )
            s.add_all([g, f])
            s.flush()
            frames[name] = f.id
            for source, status in (("ai", "USE"), ("user", user)):
                if status:
                    s.add(
                        Disposition(
                            asset_id=a.id,
                            segment_id=g.id,
                            anchor_start_ticks=0,
                            anchor_end_ticks=90000,
                            source=source,
                            status=status,
                            updated_at=T,
                        )
                    )
    with project.db.session() as s:
        cover = project_cards.compute(s)["cover"]
    project.close()
    return cover, frames


def test_cover_skips_clips_the_user_rejected(tmp_path: Path) -> None:
    cover, f = _cover(
        tmp_path,
        [("best", 0.9, "REJECT"), ("good", 0.7, None), ("ok", 0.5, None), ("fine", 0.4, None)],
    )
    assert cover == [f["good"], f["ok"], f["fine"]]


def test_the_fallback_also_skips_rejected_clips(tmp_path: Path) -> None:
    """Fewer than three USE clips: the rest are filled from other clips, never a rejected one."""
    cover, f = _cover(tmp_path, [("best", 0.9, "REJECT"), ("good", 0.7, None)])
    assert cover == [f["good"]]
    assert f["best"] not in cover
