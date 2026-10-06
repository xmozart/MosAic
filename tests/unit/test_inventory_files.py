"""S5 "Show files" lists exactly the files of its Needs-attention row (ADR 0040)."""

from __future__ import annotations

from pathlib import Path

from mosaic.library.inventory_view import inventory, inventory_files
from mosaic.storage import provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, MediaFile
from mosaic.storage.projects import init_project

T = "2025-06-02T09:00:00+00:00"


def test_rows_with_one_reason_and_different_fixes_list_their_own_files(tmp_path: Path) -> None:
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    reason = "This video format can't be read."
    files = [("a.R3D", "Export as MP4."), ("b.R3D", "Export as MP4."), ("c.BRAW", None)]
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        for rel, fix in files:
            a = Asset(
                kind="unsupported",
                status="unsupported",
                profile="generic",
                group_key=f"unsupported:{rel}",
                reason=reason,
                suggested_fix=fix,
                provenance_id=prov,
                created_at=T,
            )
            s.add(a)
            s.flush()
            s.add(
                MediaFile(
                    rel_path=f"cards/{rel}",
                    size=10,
                    mtime_ns=0,
                    fingerprint="",
                    media_type="video",
                    status="unsupported",
                    reason=reason,
                    suggested_fix=fix,
                    asset_id=a.id,
                    created_at=T,
                )
            )
    with project.db.session() as s:
        rows = [r for r in inventory(s)["attention"] if r["kind"] == "unreadable"]
        assert sorted(r["count"] for r in rows) == [1, 2]
        for r in rows:
            listed = inventory_files(s, "unreadable", r["group"])["items"]
            assert len(listed) == r["count"], "the list matches the row it came from"
            if r["count"] == 1:
                assert r["example"] == "c.BRAW"
                assert listed[0]["path"] == "cards/c.BRAW"
    project.close()
