"""Library paging on a seeded project (ADR 0031): ties, undated clips, unknown cameras,
hidden kinds and effective dispositions, deterministically."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mosaic.library import browse
from mosaic.storage import provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, Device, Disposition, Segment, Shot
from mosaic.storage.projects import Project, init_project

T1 = "2025-06-02T09:00:00+00:00"
T2 = "2025-06-03T08:00:00+00:00"


def _project(tmp_path: Path) -> Project:
    control = ControlDB()
    return init_project(control, control.local_principal, tmp_path)


def _seed(project: Project) -> dict[str, int]:
    ids: dict[str, int] = {}
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        cam = Device(key="cam", label="Cam A")
        s.add(cam)
        s.flush()

        def asset(name: str, time: str | None, device: int | None, **kw: Any) -> None:
            a = Asset(
                kind=kw.get("kind", "video"),
                status=kw.get("status", "ok"),
                profile="generic",
                group_key=name,
                capture_time=time,
                device_id=device,
                tb="1/90000",
                duration_ticks=90000,
                provenance_id=prov,
                created_at=T1,
            )
            s.add(a)
            s.flush()
            ids[name] = a.id

        asset("b_tie", T1, cam.id)
        asset("a_tie", T1, cam.id)  # same time: the id breaks the tie
        asset("day2", T2, None)  # unknown camera
        asset("undated", None, cam.id)  # sorts last, "No date"
        asset("photo", T2, cam.id, kind="photo")
        asset("broken", T1, cam.id, status="unsupported")  # not shown
        asset("sound", T1, cam.id, kind="audio")  # not a shown kind
        shot = Shot(
            asset_id=ids["b_tie"],
            index=0,
            start_ticks=0,
            end_ticks=90000,
            method="adaptive",
            provenance_id=prov,
        )
        s.add(shot)
        s.flush()
        for i, (ai, user) in enumerate([("USE", "REJECT"), ("USE", None), ("MAYBE", None)]):
            g = Segment(
                asset_id=ids["b_tie"],
                shot_id=shot.id,
                index=i,
                start_ticks=i * 30000,
                end_ticks=(i + 1) * 30000,
                usable_start_ticks=i * 30000,
                usable_end_ticks=(i + 1) * 30000,
                provenance_id=prov,
            )
            s.add(g)
            s.flush()
            for source, status in (("ai", ai), ("user", user)):
                if status:
                    s.add(
                        Disposition(
                            asset_id=ids["b_tie"],
                            segment_id=g.id,
                            anchor_start_ticks=g.start_ticks,
                            anchor_end_ticks=g.end_ticks,
                            source=source,
                            status=status,
                            updated_at=T1,
                        )
                    )
    return ids


def _walk(project: Project, group: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    cursor = None
    with project.db.session() as s:
        while True:
            page = browse.page(s, group, cursor, 1)
            if page.groups is not None:
                groups = page.groups
            items += page.items
            cursor = page.next_cursor
            if cursor is None:
                return items, groups


def test_day_order_ties_undated_and_hidden(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ids = _seed(project)
    items, groups = _walk(project, "day")
    names = {v: k for k, v in ids.items()}
    assert [names[it["asset_id"]] for it in items] == [
        *sorted(["a_tie", "b_tie"], key=lambda n: ids[n]),
        *sorted(["day2", "photo"], key=lambda n: ids[n]),
        "undated",
    ]
    assert [(g["key"], g["label"], g["count"]) for g in groups] == [
        ("2025-06-02", "Day 1 · 2025-06-02", 2),
        ("2025-06-03", "Day 2 · 2025-06-03", 2),
        ("unknown", "No date", 1),
    ]
    assert items[-1]["group"] == "unknown"
    project.close()


def test_camera_order_and_unknown_camera(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ids = _seed(project)
    items, groups = _walk(project, "camera")
    assert items[0]["asset_id"] == ids["day2"], "unknown camera (0) first"
    assert items[0]["group"] == "0"
    assert items[-1]["asset_id"] == ids["undated"], "undated last within its camera"
    assert [(g["label"], g["count"]) for g in groups] == [("Unknown camera", 1), ("Cam A", 4)]
    project.close()


def test_user_decisions_override_the_analysis_in_counts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ids = _seed(project)
    items, _ = _walk(project, "day")
    clip = next(it for it in items if it["asset_id"] == ids["b_tie"])
    assert clip["segments"] == 3
    assert clip["dispositions"] == {"REJECT": 1, "USE": 1, "MAYBE": 1, "user": 1}
    project.close()


@pytest.mark.parametrize(
    ("group", "values"),
    [
        ("day", [{"x": 1}, 2]),
        ("day", ["2025", "3"]),
        ("day", ["2025", True]),
        ("camera", ["a", "2025", 3]),
        ("day", ["2025"]),
    ],
)
def test_malformed_cursors_are_rejected(group: str, values: list[Any]) -> None:
    with pytest.raises(browse.BadCursorError):
        browse.decode_cursor(browse.encode_cursor(values), group)
