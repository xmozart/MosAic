"""Camera profiles (M1 step 8, MEDIA_SUPPORT.md §2, ADR 0024) on synthetic stand-ins for
Insta360, DJI, Nikon and GoPro TimeWarp: classification (full, analysis_only, unsupported
with a reason and fix), chapters, sidecars, and 360 footage kept out of edits."""

from __future__ import annotations

import os
from collections.abc import Iterator
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.devtools.corpus import CorpusGenerator
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.storage.models_project import Asset, AssetFile, MediaFile, Sidecar
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def cameras(
    tmp_path_factory: pytest.TempPathFactory, ffmpeg_bin: FFmpegBinaries
) -> Iterator[tuple[Any, Any]]:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.conftest import SHARED_MODELS

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOSAIC_HOME", str(tmp_path_factory.mktemp("home-cameras")))
        if "MOSAIC_MODELS_DIR" not in os.environ:
            mp.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
        mp.setenv("MOSAIC_STT_MODEL", os.environ.get("MOSAIC_STT_MODEL", "small"))
        root = tmp_path_factory.mktemp("cameras") / "trip"
        CorpusGenerator(root, ffmpeg_bin).generate(only={"cameras"})
        control = ControlDB()
        ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
        project = init_project(control, control.local_principal, root)
        job = submit_analysis(LocalExecutor(JobStore(control.db)), control.local_principal, project)
        assert run_job(control, job, timeout=1800) == "done"
        yield project, control
        project.close()


def _asset(project: Any, name: str) -> tuple[Asset, list[str]]:
    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == name))
        assert aid is not None, name
        asset = s.get(Asset, aid)
        assert asset is not None
        files = list(
            s.scalars(
                select(MediaFile.rel_path)
                .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
                .where(AssetFile.asset_id == aid)
                .order_by(AssetFile.order)
            )
        )
        s.expunge(asset)
    return asset, files


def _file(project: Any, name: str) -> MediaFile:
    with project.db.session() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == name))
        assert mf is not None, name
        s.expunge(mf)
        return mf


def test_insta360(cameras: tuple[Any, Any]) -> None:
    from mosaic.media.proxy import load_proxy

    project, _ = cameras
    flat, _ = _asset(project, "VID_20250301_101500_00_001.mp4")
    assert (flat.profile, flat.status) == ("insta360", "ok")
    assert "analysis_only" not in flat.flags
    assert flat.camera_make == "Insta360"
    for name, projection in (
        ("VID_20250301_102000_00_002.insv", "dfisheye"),
        ("VID_20250301_103000_00_003.insv", "fisheye"),
        ("VID_20250301_104000_00_004.insv", "fisheye"),
    ):
        asset, _ = _asset(project, name)
        assert asset.profile == "insta360", name
        assert {"analysis_only", f"projection:{projection}"} <= set(asset.flags), name
        assert "forward view" in (asset.reason or ""), "the owner sees why"
        assert "Insta360 Studio" in (asset.suggested_fix or "")
        px = load_proxy(project, asset.id)
        assert Fraction(px.width, px.height) == Fraction(16, 9), "a forward view"
    back, _ = _asset(project, "VID_20250301_104000_10_004.insv")
    assert back.status == "deferred"
    assert "front lens" in (back.reason or "")
    with project.db.session() as s:
        lrv = s.scalar(
            select(Sidecar)
            .join(MediaFile, MediaFile.id == Sidecar.media_file_id)
            .where(MediaFile.rel_path == "LRV_20250301_104000_01_004.lrv")
        )
        assert lrv is not None
        front = _file(project, "VID_20250301_104000_00_004.insv")
        assert lrv.owner_media_file_id == front.id
        assert not lrv.proxy_candidate, "a 360 preview is never the analysis proxy"


def test_360_is_analyzed_but_never_edited(cameras: tuple[Any, Any]) -> None:
    from mosaic.editing.retrieval import retrieve
    from mosaic.storage.models_project import Segment, VisualObservation

    project, _ = cameras
    asset, _ = _asset(project, "VID_20250301_102000_00_002.insv")
    with project.db.session() as s:
        segs = list(s.scalars(select(Segment.id).where(Segment.asset_id == asset.id)))
        observed = s.scalar(
            select(VisualObservation.id).where(VisualObservation.segment_id.in_(segs)).limit(1)
        )
        cands, counts = retrieve(s, Fraction(1), Fraction(30))
    assert segs, "sampled and segmented through the forward view"
    assert observed is not None, "and seen by vision"
    assert not {c.asset_id for c in cands} & {asset.id}
    assert counts["analysis_only"] >= 3


def test_dji_chapters_and_sidecars(cameras: tuple[Any, Any]) -> None:
    project, _ = cameras
    first, files = _asset(project, "DJI_0001.MP4")
    assert first.profile == "dji"
    assert files == ["DJI_0001.MP4", "DJI_0002.MP4"], "chapters continue in time"
    third, files3 = _asset(project, "DJI_0003.MP4")
    assert third.id != first.id
    assert files3 == ["DJI_0003.MP4"], "a gap in time is a new recording"
    assert first.camera_make == "DJI"
    with project.db.session() as s:
        rows = {
            mf.rel_path: sc
            for sc, mf in s.execute(
                select(Sidecar, MediaFile).join(MediaFile, MediaFile.id == Sidecar.media_file_id)
            )
        }
    owner = _file(project, "DJI_0001.MP4").id
    assert rows["DJI_0001.LRF"].owner_media_file_id == owner
    assert rows["DJI_0001.LRF"].status == "valid"
    assert rows["DJI_0001.SRT"].owner_media_file_id == owner
    assert rows["DJI_0001.SRT"].kind == "srt"


def test_nikon_gopro_timelapse_and_unsupported_catalog(cameras: tuple[Any, Any]) -> None:
    project, _ = cameras
    nikon, _ = _asset(project, "DSC_0001.MOV")
    assert nikon.profile == "nikon_z"
    assert nikon.camera_make == "NIKON CORPORATION"
    timelapse, _ = _asset(project, "GX010500.MP4")
    assert timelapse.profile == "gopro"
    assert "timelapse" in timelapse.flags
    for name, words in (
        ("DSC_0002.NEV", ("N-RAW", "NX Studio")),
        ("A001_C001.braw", ("Blackmagic RAW", "DaVinci Resolve")),
    ):
        mf = _file(project, name)
        assert mf.status == "unsupported", name
        assert words[0] in (mf.reason or ""), (name, mf.reason)
        assert words[1] in (mf.suggested_fix or ""), (name, mf.suggested_fix)


def test_older_classification_is_redone(cameras: tuple[Any, Any]) -> None:
    """A file classified unsupported under an older probe version (before these profiles)
    is probed again on the next analysis and gets its new classification."""
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis

    project, control = cameras
    with project.write() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == "DSC_0001.MOV"))
        assert mf is not None
        mf.status, mf.reason, mf.probe_key = "unsupported", "old reason", "probe-old-version"
    job = submit_analysis(LocalExecutor(JobStore(control.db)), control.local_principal, project)
    assert run_job(control, job, timeout=900) == "done"
    mf2 = _file(project, "DSC_0001.MOV")
    assert mf2.status == "ok"
    assert mf2.reason is None
    nikon, _ = _asset(project, "DSC_0001.MOV")
    assert nikon.profile == "nikon_z"
