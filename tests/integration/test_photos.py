"""Photos through the pipeline (M1 step 9a, MEDIA_SUPPORT.md §2–3, ADR 0025): ingest of
JPEG, HEIC and NEF previews, Live Photo pairing by content identifier, and photos in
samples, embeddings, mosaics, vision and dispositions, but not in edits yet."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.devtools.corpus import CorpusGenerator
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.storage.models_project import (
    Asset,
    Disposition,
    Embedding,
    MediaFile,
    MosaicTile,
    SampleFrame,
    Segment,
    Shot,
    TechMetric,
    VisualObservation,
)
from tests.support.photos import HEIC, jpeg, raw_with_preview
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]
LIVE = "LIVE-PHOTO-1"


@pytest.fixture(scope="module")
def photos(
    tmp_path_factory: pytest.TempPathFactory, ffmpeg_bin: FFmpegBinaries, corpus_dir: Path
) -> Iterator[Any]:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.conftest import SHARED_MODELS

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOSAIC_HOME", str(tmp_path_factory.mktemp("home-photos")))
        if "MOSAIC_MODELS_DIR" not in os.environ:
            mp.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
        mp.setenv("MOSAIC_STT_MODEL", os.environ.get("MOSAIC_STT_MODEL", "small"))
        root = tmp_path_factory.mktemp("photos") / "trip"
        root.mkdir()
        apple = {"make": "Apple", "model": "iPhone 15 Pro"}
        jpeg(
            root / "IMG_1000.JPG",
            seed=41,
            taken="2025:03:01 10:00:00",
            offset="+01:00",
            content_id=LIVE,
            **apple,
        )
        # The Live Photo's motion half, named differently: paired by identifier.
        CorpusGenerator(root, ffmpeg_bin)._video(
            "IMG_E1000.MOV",
            seconds=2,
            seed=41,
            metadata=(
                ("com.apple.quicktime.make", "Apple"),
                ("com.apple.quicktime.content.identifier", LIVE),
            ),
        )
        jpeg(root / "beach.jpg", seed=42, size=(640, 480))
        raw_with_preview(root / "DSC_0001.NEF", orientation=1)
        shutil.copy(HEIC, root / "IMG_2000.HEIC")
        (root / "pano.insp").write_bytes(b"\xff\xd8\xff\xe0 insp")
        shutil.copy(corpus_dir / "A001_basic.mp4", root / "A001_basic.mp4")
        control = ControlDB()
        ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
        project = init_project(control, control.local_principal, root)
        job = submit_analysis(LocalExecutor(JobStore(control.db)), control.local_principal, project)
        assert run_job(control, job, timeout=1200) == "done"
        yield project
        project.close()


def _asset_of(project: Any, name: str) -> Asset:
    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == name))
        asset = s.get(Asset, aid)
        assert asset is not None, name
        s.expunge(asset)
        return asset


def test_live_photo_pairs_by_identifier(photos: Any) -> None:
    live = _asset_of(photos, "IMG_1000.JPG")
    assert (live.kind, live.status, live.profile) == ("live_photo", "ok", "iphone")
    assert _asset_of(photos, "IMG_E1000.MOV").id == live.id, "both halves in one asset"
    assert live.capture_time == "2025-03-01T10:00:00+01:00"
    assert live.camera_make == "Apple"


def test_formats_are_ingested(photos: Any) -> None:
    nef = _asset_of(photos, "DSC_0001.NEF")
    assert (nef.kind, nef.status, nef.profile) == ("photo", "ok", "nikon_z")
    assert nef.camera_make == "NIKON CORPORATION"
    assert (nef.display_width, nef.display_height) == (640, 400), "the embedded preview"
    heic = _asset_of(photos, "IMG_2000.HEIC")
    assert (heic.kind, heic.status) == ("photo", "ok")
    assert (heic.display_width, heic.display_height) == (320, 240)
    with photos.db.session() as s:
        insp = s.scalar(select(MediaFile).where(MediaFile.rel_path == "pano.insp"))
        assert insp is not None
        assert insp.status == "unsupported"
        assert "360° photos" in (insp.reason or "")


def test_photos_are_analyzed_like_one_frame_clips(photos: Any) -> None:
    for name in ("beach.jpg", "DSC_0001.NEF", "IMG_2000.HEIC", "IMG_1000.JPG"):
        asset = _asset_of(photos, name)
        with photos.db.session() as s:
            shots = list(s.scalars(select(Shot).where(Shot.asset_id == asset.id)))
            samples = list(s.scalars(select(SampleFrame).where(SampleFrame.asset_id == asset.id)))
            metrics = {
                m.name for m in s.scalars(select(TechMetric).where(TechMetric.asset_id == asset.id))
            }
            segs = list(s.scalars(select(Segment).where(Segment.asset_id == asset.id)))
            seg_ids = [g.id for g in segs]
            emb = s.scalar(
                select(Embedding).where(
                    Embedding.owner_kind == "photo_segment", Embedding.owner_id.in_(seg_ids)
                )
            )
            tile = s.scalar(select(MosaicTile).where(MosaicTile.segment_id.in_(seg_ids)))
            obs = s.scalar(
                select(VisualObservation).where(VisualObservation.segment_id.in_(seg_ids))
            )
            disp = s.scalar(select(Disposition).where(Disposition.segment_id.in_(seg_ids)))
        assert [sh.method for sh in shots] == ["photo"], name
        assert [sm.reason for sm in samples] == ["photo"], name
        assert samples[0].image_key
        assert photos.artifacts.exists("frame", samples[0].image_key)
        assert {"sharpness", "exposure_mean", "clip_high"} <= metrics, name
        assert len(segs) == 1, name
        assert emb is not None, f"{name}: segment embedding"
        assert tile is not None, f"{name}: in a contact sheet"
        assert obs is not None, f"{name}: seen by vision"
        assert disp is not None, f"{name}: has a disposition"
        codes = {r["code"] for r in disp.reasons}
        assert not codes & {"too_short", "accidental_recording"}, (name, codes)


def test_photos_stay_out_of_edits_for_now(photos: Any) -> None:
    from mosaic.editing.retrieval import retrieve

    with photos.db.session() as s:
        cands, _ = retrieve(s, Fraction(1), Fraction(30))
        kinds = {s.scalar(select(Asset.kind).where(Asset.id == c.asset_id)) for c in cands}
    assert cands
    assert kinds == {"video"}


def test_photo_vectors_stay_out_of_video_similarity(photos: Any) -> None:
    with photos.db.session() as s:
        photo_segs = set(
            s.scalars(
                select(Segment.id)
                .join(Asset, Asset.id == Segment.asset_id)
                .where(Asset.kind.in_(("photo", "live_photo")))
            )
        )
        kinds = set(
            s.scalars(select(Embedding.owner_kind).where(Embedding.owner_id.in_(photo_segs)))
        )
        grouped = set(s.scalars(select(Segment.id).where(Segment.similarity_group_id.is_not(None))))
    assert "photo_segment" in kinds
    assert not grouped & photo_segs
