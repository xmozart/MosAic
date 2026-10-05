"""L0 inventory over the synthetic corpus (M0 step 4)."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from mosaic.core.modes import UnknownModeError
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.pipeline import submit_analysis
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    MediaFile,
    MediaStream,
    Segment,
    Shot,
    Sidecar,
)
from mosaic.storage.projects import init_project
from tests.support.runner import run_job

pytestmark = pytest.mark.integration


def _hashes(root: Path) -> dict[str, str]:
    """Every original under root (recursive), excluding MosAic's own workspace."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and rel.parts[0] != "MosAic" and p.name != ".mosaic-project.json":
            try:
                out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
            except PermissionError:
                out[rel.as_posix()] = "unreadable"
    return out


def test_l0_inventory_of_synthetic_corpus(corpus_dir: Path, tmp_path: Path) -> None:
    root = tmp_path / "trip"
    shutil.copytree(corpus_dir, root)
    (root / "day2").mkdir()
    shutil.copy(root / "A002_basic.mp4", root / "day2" / "clip.mp4")
    (root / "voice.wav").write_bytes(b"RIFF....WAVEfmt ")  # unreadable audio → unsupported
    shutil.copy(root / "A001_basic.mp4", root / "ambience.m4a")  # audio container → deferred
    locked = root / "locked.mp4"
    shutil.copy(root / "A002_basic.mp4", locked)
    locked.chmod(0)
    before = _hashes(root)
    control = ControlDB()
    project = init_project(control, control.local_principal, root)
    ex = LocalExecutor(JobStore(control.db))
    with pytest.raises(UnknownModeError):
        submit_analysis(ex, control.local_principal, project, "deep")
    job = submit_analysis(ex, control.local_principal, project)
    assert run_job(control, job) == "done"

    with project.db.session() as s:
        files = {m.rel_path: m for m in s.scalars(select(MediaFile))}
        assets = {a.id: a for a in s.scalars(select(Asset))}

        def asset_of(name: str) -> Asset:
            aid = files[name].asset_id
            assert aid is not None, name
            return assets[aid]

        chap = asset_of("GX010042.MP4")
        assert asset_of("GX020042.MP4").id == chap.id
        amap = list(
            s.scalars(
                select(AssetFile).where(AssetFile.asset_id == chap.id).order_by(AssetFile.order)
            )
        )
        assert [a.media_file_id for a in amap] == [
            files["GX010042.MP4"].id,
            files["GX020042.MP4"].id,
        ]
        assert amap[1].logical_start_ticks == amap[0].duration_ticks
        assert chap.duration_ticks == amap[0].duration_ticks + amap[1].duration_ticks
        assert chap.profile == "gopro"

        r90 = asset_of("rotated_90.mp4")
        assert (r90.rotation, r90.display_width, r90.display_height) == (90, 360, 640)
        assert asset_of("hlg.mov").color_hint == "hlg"
        assert asset_of("pq.mov").color_hint == "pq"
        assert asset_of("hfr_120.mp4").hfr
        assert asset_of("vfr.mp4").vfr
        assert not any(a.vfr for a in assets.values() if a.group_key != "generic:vfr.mp4")
        assert asset_of("no_audio.mp4").audio_stream_index is None
        multi = asset_of("multi_audio.mov")
        chosen = s.scalar(
            select(MediaStream).where(
                MediaStream.media_file_id == files["multi_audio.mov"].id,
                MediaStream.stream_index == multi.audio_stream_index,
            )
        )
        assert chosen is not None
        assert chosen.channels == 2

        corrupt = asset_of("corrupt.mp4")
        assert (corrupt.kind, corrupt.status) == ("unsupported", "unsupported")
        assert corrupt.reason
        assert corrupt.suggested_fix
        photo = asset_of("IMG_0001.jpg")
        assert (photo.kind, photo.status) == ("photo", "ok")  # analyzed since M1 (ADR 0025)
        assert (photo.display_width, photo.display_height) == (480, 640), "EXIF orientation"

        off = s.scalar(
            select(MediaStream).where(
                MediaStream.media_file_id == files["start_offset.mp4"].id,
                MediaStream.codec_type == "video",
            )
        )
        assert off is not None
        assert off.start_pts > 0
        fr = s.scalar(
            select(MediaStream).where(
                MediaStream.media_file_id == files["full_range.mp4"].id,
                MediaStream.codec_type == "video",
            )
        )
        assert fr is not None
        assert fr.color_range == "pc"
        h10 = s.scalar(
            select(MediaStream).where(
                MediaStream.media_file_id == files["hevc10_5994.mov"].id,
                MediaStream.codec_type == "video",
            )
        )
        assert h10 is not None
        assert h10.bit_depth == 10
        assert h10.rate == "60000/1001"

        sidecars = {
            files_by_id.rel_path: sc
            for sc in s.scalars(select(Sidecar))
            for files_by_id in [s.get(MediaFile, sc.media_file_id)]
            if files_by_id
        }
        lrf = sidecars["GL010042.LRF"]
        assert lrf.status == "valid", lrf.reason
        assert sidecars["GL020042.LRF"].proxy_candidate
        if os.geteuid() != 0:  # root (some CI containers) can read a chmod-000 file
            assert files["locked.mp4"].status == "unsupported"
            assert "Cannot read" in (files["locked.mp4"].reason or "")
        assert asset_of("day2/clip.mp4").kind == "video"
        # A byte-identical copy shares the proxy blob but still gets its own analysis rows.
        for name in ("day2/clip.mp4", "A002_basic.mp4"):
            aid = asset_of(name).id
            assert s.scalar(select(Shot.id).where(Shot.asset_id == aid).limit(1)), name
            assert s.scalar(select(Segment.id).where(Segment.asset_id == aid).limit(1)), name
        assert asset_of("ambience.m4a").status == "deferred"
        assert asset_of("voice.wav").status == "unsupported"
        assert asset_of("manifest.json").kind == "unsupported"
        assert chap.provenance_id
        probe_key = files["A001_basic.mp4"].probe_key
        assert probe_key is not None
    assert project.artifacts.get_json("probe", probe_key)["streams"]

    # Re-analysis reuses every probe; originals are untouched.
    store = JobStore(control.db)
    again = submit_analysis(ex, control.local_principal, project)
    assert run_job(control, again) == "done"
    events = [e.event for e in store.events(again)]
    assert "skipped_existing" in events
    probe_tasks = [t for t in store.tasks(again) if t.kind == "media.probe"]
    started = {e.task_id for e in store.events(again) if e.event == "started"}
    assert not started & {t.id for t in probe_tasks}
    # Originals (including subfolders and the unreadable file) are untouched.
    assert _hashes(root) == before
    locked.chmod(0o644)
    assert locked.read_bytes() == (root / "A002_basic.mp4").read_bytes()
    project.close()


def _asset_status(project, rel: str) -> tuple[str, str] | None:  # type: ignore[no-untyped-def]
    with project.db.session() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == rel))
        if mf is None or mf.asset_id is None:
            return None
        a = s.get(Asset, mf.asset_id)
        return (a.kind, a.status) if a else None


def test_reanalysis_reconciles_fixed_deleted_and_offline_files(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    from mosaic.cli.dev import cli as dev_cli
    from mosaic.media import inventory, scan

    root = tmp_path / "trip"
    root.mkdir()
    for name in ("A001_basic.mp4", "A002_basic.mp4", "corrupt.mp4", "no_audio.mp4"):
        shutil.copy(corpus_dir / name, root / name)
    control = ControlDB()
    project = init_project(control, control.local_principal, root)
    ex = LocalExecutor(JobStore(control.db))
    assert run_job(control, submit_analysis(ex, control.local_principal, project)) == "done"
    assert _asset_status(project, "corrupt.mp4") == ("unsupported", "unsupported")

    out = CliRunner().invoke(dev_cli, ["inspect", str(root)])
    assert out.exit_code == 0, out.output
    assert "reason: Could not read the file" in out.output
    assert "fix: Check that the copy finished" in out.output

    # The user follows the fix (copies a good file), deletes one clip, and one goes offline.
    shutil.copy(corpus_dir / "vfr.mp4", root / "corrupt.mp4")
    (root / "no_audio.mp4").unlink()
    offline_name = "A002_basic.mp4"
    real_scan_offline = scan.is_offline
    monkeypatch.setattr(
        scan,
        "is_offline",
        lambda st: st.st_size == (root / offline_name).stat().st_size or real_scan_offline(st),
    )
    monkeypatch.setattr(inventory, "is_offline", scan.is_offline)
    assert run_job(control, submit_analysis(ex, control.local_principal, project)) == "done"
    assert _asset_status(project, "corrupt.mp4") == ("video", "ok")
    with project.db.session() as s:
        statuses = {a.group_key: a.status for a in s.scalars(select(Asset))}
        files = {m.rel_path: m for m in s.scalars(select(MediaFile))}
    assert statuses["unsupported:corrupt.mp4"] == "missing"
    assert statuses["generic:no_audio.mp4"] == "missing"
    assert statuses["generic:A002_basic.mp4"] == "missing"
    assert files["no_audio.mp4"].status == "missing"
    assert files[offline_name].status == "offline"
    out = CliRunner().invoke(dev_cli, ["inspect", str(root)])
    assert "offline  A002_basic.mp4" in out.output
    project.close()
