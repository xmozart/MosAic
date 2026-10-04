"""L1 visual analysis (M0 step 6): shots, samples, tech metrics, shake."""

from __future__ import annotations

import itertools
import json
import statistics
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import select

from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.proxy import load_proxy
from mosaic.storage.models_project import Asset, AssetFile, MediaFile, SampleFrame, Shot, TechMetric
from mosaic.storage.projects import Project
from tests.support.media import source_frame_times

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def analyzed(analyzed_corpus: Project) -> Project:
    return analyzed_corpus


def _cases(project: Project) -> dict[str, dict]:  # type: ignore[type-arg]
    data = json.loads((project.root / "manifest.json").read_text())
    return {c["files"][0]: c for c in data["cases"] if c["files"] and c.get("scene_frames")}


def _asset_for(project: Project, name: str) -> tuple[Asset, list[Path]]:
    with project.db.session() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == name))
        assert mf is not None
        assert mf.asset_id is not None
        asset = s.get(Asset, mf.asset_id)
        assert asset is not None
        files = [
            project.root / r
            for r in s.scalars(
                select(MediaFile.rel_path)
                .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
                .where(AssetFile.asset_id == asset.id)
                .order_by(AssetFile.order)
            )
        ]
        return asset, files


def test_shot_boundaries_match_scene_changes(analyzed: Project, ffmpeg_bin: FFmpegBinaries) -> None:
    for name, case in _cases(analyzed).items():
        asset, files = _asset_for(analyzed, name)
        tb = Fraction(asset.tb)
        px = load_proxy(analyzed, asset.id)
        times = source_frame_times(ffmpeg_bin, files)
        scene = case["scene_frames"]
        end = asset.duration_ticks * tb
        # The adaptive detector compares each frame with ±2 neighbours, so a change in the
        # last two proxy frames cannot be detected (as in PySceneDetect).
        expected = [
            times[k] for k in range(scene, len(times), scene) if end - times[k] > 2 / px.rate
        ]
        with analyzed.db.session() as s:
            shots = list(
                s.scalars(select(Shot).where(Shot.asset_id == asset.id).order_by(Shot.index))
            )
        starts = [sh.start_ticks * tb for sh in shots[1:]]
        assert shots[0].start_ticks == 0, name
        assert shots[-1].end_ticks == asset.duration_ticks, name
        assert all(a.end_ticks == b.start_ticks for a, b in itertools.pairwise(shots))
        # Each synthetic scene change is found within one proxy frame, and nothing else is.
        assert len(starts) == len(expected), f"{name}: {len(starts)} cuts, want {len(expected)}"
        for got, want in zip(starts, expected, strict=True):
            assert abs(got - want) <= 1 / px.rate, (
                f"{name}: cut at {float(got):.3f}s, want {float(want):.3f}s"
            )


def test_samples_metrics_and_thumbnails(analyzed: Project) -> None:
    with analyzed.db.session() as s:
        shots = {sh.id: sh for sh in s.scalars(select(Shot))}
        samples = list(s.scalars(select(SampleFrame)))
        metrics = list(s.scalars(select(TechMetric)))
    assert samples
    per_shot_scene: dict[int, int] = {}
    for sm in samples:
        sh = shots[sm.shot_id]
        assert sh.start_ticks <= sm.ticks < sh.end_ticks or sh.start_ticks == sh.end_ticks
        if sm.reason == "scene":
            per_shot_scene[sm.shot_id] = per_shot_scene.get(sm.shot_id, 0) + 1
            assert sm.kept, "scene-change samples are always kept"
        if sm.kept:
            assert sm.image_key
            assert analyzed.artifacts.exists("frame", sm.image_key)
        else:
            assert sm.dup_of is not None
    assert set(per_shot_scene.values()) == {1}
    assert len(per_shot_scene) == len(shots)
    names = {m.name for m in metrics}
    assert {
        "sharpness",
        "exposure_mean",
        "clip_low",
        "clip_high",
        "noise",
        "obstruction",
        "shake",
        "motion",
    } <= names
    assert all(m.percentile is not None and 0 <= m.percentile <= 1 for m in metrics)


def test_shake_metric_separates_shaky_from_steady(analyzed: Project) -> None:
    def median_shake(name: str) -> float:
        asset, _ = _asset_for(analyzed, name)
        with analyzed.db.session() as s:
            vals = list(
                s.scalars(
                    select(TechMetric.value).where(
                        TechMetric.asset_id == asset.id, TechMetric.name == "shake"
                    )
                )
            )
        return statistics.median(vals)

    shaky, steady = median_shake("shaky.mp4"), median_shake("A001_basic.mp4")
    assert shaky > 0.005, shaky
    assert shaky > 5 * steady, (shaky, steady)


def test_samples_are_the_frames_at_their_ticks(
    analyzed: Project, ffmpeg_bin: FFmpegBinaries
) -> None:
    """Invariant 4: each kept sample's image is the source frame at ``SampleFrame.ticks``
    (±1 frame), read back from the stored thumbnail's barcode."""
    import io

    import numpy as np
    from PIL import Image

    from mosaic.devtools import barcode
    from tests.support.media import nearest_index

    checked = 0
    for name in ("A001_basic.mp4", "vfr.mp4", "GX010042.MP4", "hfr_120.mp4", "rotated_90.mp4"):
        asset, files = _asset_for(analyzed, name)
        tb = Fraction(asset.tb)
        times = source_frame_times(ffmpeg_bin, files)
        with analyzed.db.session() as s:
            samples = list(
                s.scalars(
                    select(SampleFrame).where(
                        SampleFrame.asset_id == asset.id, SampleFrame.kept.is_(True)
                    )
                )
            )
        assert samples, name
        for sm in samples:
            assert sm.image_key is not None
            img = np.asarray(
                Image.open(io.BytesIO(analyzed.artifacts.get_bytes("frame", sm.image_key))).convert(
                    "RGB"
                )
            )
            d = barcode.decode(img)
            assert d is not None, f"{name}: unreadable sample {sm.id}"
            want = nearest_index(times, sm.ticks * tb)
            assert abs(d.index - want) <= 1, (
                f"{name}: sample at {sm.ticks} shows {d.index}, want {want}"
            )
            checked += 1
    assert checked > 20
