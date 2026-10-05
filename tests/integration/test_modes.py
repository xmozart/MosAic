"""Analysis modes (M1 step 4; M1 acceptance 5): Quick on the synthetic corpus, then
deepening the trip to Thorough reuses every L0/L1 artifact."""

from __future__ import annotations

import itertools
import os
import shutil
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.core.modes import PRESETS
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.library.review import DeepenScope, plan_deepen, submit_deepen
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.pipeline import submit_analysis
from mosaic.media.proxy import (
    QUICK_BITRATE,
    load_proxy,
    plan_for,
    proxy_frame_to_source_ticks,
)
from mosaic.storage.models_project import (
    Artifact,
    Asset,
    AssetFile,
    DeepReview,
    MediaFile,
    MediaStream,
    Mosaic,
    SampleFrame,
    Shot,
    Summary,
)
from tests.support.media import decode_barcodes, nearest_index, source_frame_times
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]

QUICK = PRESETS["quick"]
L01_KINDS = ("probe", "proxy", "tickmap", "visual", "audio", "embed", "segments", "telemetry")


@pytest.fixture(scope="module")
def quick(
    corpus_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[Any, Any, int]]:
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.conftest import SHARED_MODELS

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOSAIC_HOME", str(tmp_path_factory.mktemp("home-quick")))
        if "MOSAIC_MODELS_DIR" not in os.environ:
            mp.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
        mp.delenv("MOSAIC_STT_MODEL", raising=False)  # the mode chooses the Whisper model
        mp.setenv("MOSAIC_EMBED_VARIANT", os.environ.get("MOSAIC_EMBED_VARIANT", "quantized"))
        root = tmp_path_factory.mktemp("quick") / "trip"
        shutil.copytree(corpus_dir, root)
        control = ControlDB()
        ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
        project = init_project(control, control.local_principal, root)
        job = submit_analysis(
            LocalExecutor(JobStore(control.db)), control.local_principal, project, "quick"
        )
        assert run_job(control, job, timeout=1800) == "done"
        yield project, control, job
        project.close()


def _asset(project: Any, first_file: str) -> tuple[Asset, list[Path]]:
    with project.db.session() as s:
        rows = list(
            s.execute(
                select(Asset, MediaFile.rel_path)
                .join(AssetFile, AssetFile.asset_id == Asset.id)
                .join(MediaFile, MediaFile.id == AssetFile.media_file_id)
                .order_by(Asset.id, AssetFile.order)
            )
        )
    files: dict[int, list[Path]] = {}
    assets: dict[int, Asset] = {}
    for a, rel in rows:
        assets[a.id] = a
        files.setdefault(a.id, []).append(project.root / rel)
    aid = next(i for i, fs in files.items() if fs[0].name == first_file)
    return assets[aid], files[aid]


def test_quick_uses_the_camera_proxy_frame_accurately(
    quick: tuple[Any, Any, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    project, _, _ = quick
    asset, files = _asset(project, "GX010042.MP4")
    plan = plan_for(project, asset.id, QUICK)
    assert plan.source == "camera"
    assert [c.rel_path for c in plan.chapters] == ["GL010042.LRF", "GL020042.LRF"]
    assert (plan.width, plan.height) == (320, 180)  # the LRF's size: never upscaled
    assert plan.bitrate == QUICK_BITRATE
    px = load_proxy(project, asset.id, QUICK)
    got = decode_barcodes(ffmpeg_bin, px.path, 320, 180)
    assert len(got) == px.frames
    # Invariant 4: tick-map times are the *original's* frames, though the pixels came
    # from the camera proxy.
    times = source_frame_times(ffmpeg_bin, files)
    for i, d in enumerate(got):
        assert d is not None, f"proxy frame {i} has no readable barcode"
        t = proxy_frame_to_source_ticks(px.tickmap, i) * px.tb
        assert abs(d.index - nearest_index(times, t)) <= 1, f"frame {i}"


def test_quick_without_a_camera_proxy_transcodes_at_540(quick: tuple[Any, Any, int]) -> None:
    project, _, _ = quick
    asset, _ = _asset(project, "A001_basic.mp4")
    q, b = plan_for(project, asset.id, QUICK), plan_for(project, asset.id)
    assert q.source == "original"
    assert q.key(project.id, "x") != b.key(project.id, "x")
    # Without a mode (previews), the proxy that exists is used: here only Quick's.
    assert load_proxy(project, asset.id).key == load_proxy(project, asset.id, QUICK).key


def test_quick_parameters_reach_every_stage(quick: tuple[Any, Any, int]) -> None:
    project, control, job = quick
    asset, _ = _asset(project, "A001_basic.mp4")
    rate = Fraction(asset.rate or "30")
    with project.db.session() as s:
        shots = list(s.scalars(select(Shot).where(Shot.asset_id == asset.id)))
        samples = list(
            s.scalars(
                select(SampleFrame)
                .where(SampleFrame.asset_id == asset.id, SampleFrame.reason == "interval")
                .order_by(SampleFrame.ticks)
            )
        )
        sheets = list(s.scalars(select(Mosaic)))
    assert {sh.method for sh in shots} <= {"threshold", "forced"}
    assert samples
    tb = Fraction(asset.tb or "1")
    per_shot: dict[int, list[int]] = {}
    for sm in samples:
        per_shot.setdefault(sm.shot_id, []).append(sm.ticks)
    for ticks in per_shot.values():
        for a, b in itertools.pairwise(ticks):
            assert (b - a) * tb >= 6 - 1 / rate, "Quick samples every 6 s"
    assert sheets
    assert {(m.cols, m.rows) for m in sheets} == {(6, 4)}
    tasks = JobStore(control.db).tasks(job)
    assert not [t for t in tasks if t.kind in ("analysis.deepen", "library.review")]
    audio = [t for t in tasks if t.kind == "audio.analyze" and t.status == "done"]
    assert audio


def _tag_two_days(project: Any) -> dict[int, int]:
    """The synthetic corpus has no capture dates: put alternate assets on two days."""
    with project.write() as s:
        assets = list(s.scalars(select(Asset).where(Asset.kind == "video").order_by(Asset.id)))
        days = {}
        for n, a in enumerate(assets):
            day = 1 + n % 2
            a.capture_time = f"2026-09-0{4 + day}T10:00:00"
            days[a.id] = day
    return days


def test_quick_to_thorough_on_one_day_reuses_l0_l1(quick: tuple[Any, Any, int]) -> None:
    """M1 acceptance 5: deepening one day adds L3 only; the new AI calls equal that
    day's candidates, and no L0/L1 artifact is added or replaced."""
    project, control, _ = quick
    days = _tag_two_days(project)
    with project.db.session() as s:
        before = set(
            s.execute(select(Artifact.kind, Artifact.key).where(Artifact.kind.in_(L01_KINDS)))
        )
        plan, _ = plan_deepen(s, DeepenScope(days=(2,)))
        whole, _ = plan_deepen(s)
    candidates = sum(len(v) for v in plan.values())
    assert candidates > 0
    assert set(plan) <= {a for a, d in days.items() if d == 2}
    assert candidates < sum(len(v) for v in whole.values()), "day 1 has candidates too"
    calls = len(fake.CALLS)
    run = submit_deepen(
        LocalExecutor(JobStore(control.db)),
        control.local_principal,
        project,
        DeepenScope(days=(2,)),
    )
    assert run.job is not None
    assert run.l2_assets == []
    assert run.candidates == candidates
    assert run_job(control, run.job, timeout=900) == "done"
    new = fake.CALLS[calls:]
    analysis = [c for c in new if c != "summary"]
    assert analysis == ["review"] * candidates, "only L3 calls, one per candidate"
    # The summaries refresh after the reviews: here two newly dated days and the trip.
    assert new.count("summary") == 3
    kinds = {t.kind for t in JobStore(control.db).tasks(run.job)}
    assert kinds == {"library.review", "library.dispositions", "library.summaries"}
    with project.db.session() as s:
        after = set(
            s.execute(select(Artifact.kind, Artifact.key).where(Artifact.kind.in_(L01_KINDS)))
        )
        reviewed = set(s.scalars(select(DeepReview.segment_id)))
    assert after == before, "no L0/L1 artifact was added or replaced"
    assert reviewed == {i for ids in plan.values() for i in ids}, "day 1 was not reviewed"
    with project.db.session() as s:
        day_refs = set(s.scalars(select(Summary.ref).where(Summary.level == "day")))
    assert day_refs == {1, 2}, "summaries number days as the editor does"


def test_silent_camera_proxy_is_not_used(quick: tuple[Any, Any, int]) -> None:
    project, _, _ = quick
    asset, _ = _asset(project, "GX010042.MP4")
    with project.write() as s:
        lrf = s.scalar(select(MediaFile).where(MediaFile.rel_path == "GL020042.LRF"))
        assert lrf is not None
        row = s.scalar(
            select(MediaStream).where(
                MediaStream.media_file_id == lrf.id, MediaStream.codec_type == "audio"
            )
        )
        assert row is not None
        saved = {c.name: getattr(row, c.name) for c in MediaStream.__table__.columns}
        s.delete(row)
    try:
        assert plan_for(project, asset.id, QUICK).source == "original"
    finally:
        with project.write() as s:
            s.add(MediaStream(**saved))
    assert plan_for(project, asset.id, QUICK).source == "camera"


def test_thorough_run_adds_the_l3_stage(
    quick: tuple[Any, Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole-project Thorough run re-analyzes at its density, then reviews candidates."""
    project, control, _ = quick
    monkeypatch.setenv("MOSAIC_STT_MODEL", "small")  # CI never downloads large-v3
    calls = len(fake.CALLS)
    job = submit_analysis(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, "thorough"
    )
    assert run_job(control, job, timeout=1800) == "done"
    with project.db.session() as s:
        days = s.scalar(select(func.count(Summary.id)).where(Summary.level == "day")) or 0
    assert fake.CALLS[calls:].count("summary") == days + 1, "each day and the trip, once"
    tasks = JobStore(control.db).tasks(job)
    deepen = [t for t in tasks if t.kind == "analysis.deepen"]
    assert len(deepen) == 1
    assert deepen[0].status == "done"
    reviews = [t for t in tasks if t.kind == "library.review"]
    assert reviews
    dispositions = [t for t in tasks if t.kind == "library.dispositions"]
    assert len(dispositions) == 2, "before L3 (candidates) and after it (merge)"
    summaries = {t.status for t in tasks if t.kind == "library.summaries"}
    assert summaries == {"skipped", "done"}, "the project stage defers to the review chain"
    with project.db.session() as s:
        sheets = list(s.scalars(select(Mosaic)))
    assert {(m.cols, m.rows) for m in sheets} == {(4, 3)}


def test_estimate_and_runs_api(quick: tuple[Any, Any, int]) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, control, _ = quick
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    base = f"/api/projects/{project.id}"
    ests = {}
    for mode in ("quick", "balanced", "thorough"):
        r = client.get(f"{base}/analysis/estimate", params={"mode": mode})
        assert r.status_code == 200, r.text
        ests[mode] = r.json()
    q, b, t = ests["quick"], ests["balanced"], ests["thorough"]
    assert q["videos"] == b["videos"] > 0
    assert q["video_seconds"] == b["video_seconds"] > 0
    assert q["cost_usd"] == [0.0, 0.0], "the fake provider costs nothing"
    assert q["l2_calls"] < b["l2_calls"] < t["l2_calls"], "24, 16, then 12 tiles per sheet"
    assert q["storage_bytes"] < b["storage_bytes"]
    assert q["l3_calls"] == b["l3_calls"] == [0, 0]
    assert t["l3_calls"][0] > 0
    assert t["wall_seconds"][1] > b["wall_seconds"][1]
    # Deepening the trip after every candidate is reviewed: no new L3 calls.
    run0 = submit_deepen(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, DeepenScope()
    )
    if run0.job is not None:
        assert run_job(control, run0.job, timeout=900) == "done"
    r = client.get(f"{base}/analysis/estimate", params={"mode": "thorough", "scope": "trip"})
    assert r.status_code == 200, r.text
    assert r.json()["l3_calls"] == [0, 0]
    assert r.json()["l2_calls"] == 0
    assert client.get(f"{base}/analysis/estimate", params={"mode": "nope"}).status_code == 422
    bad = client.get(f"{base}/analysis/estimate", params={"mode": "quick", "scope": "trip"})
    assert bad.status_code == 422
    # A selection that holds no candidate: nothing to add, the id is reported back.
    run = client.post(
        f"{base}/analysis-runs",
        json={"mode": "thorough", "scope": {"kind": "selection", "segment_ids": [999999]}},
    )
    assert run.status_code == 202, run.text
    assert run.json()["job_id"] is None
    assert run.json()["dropped"] == [999999]
    custom = client.post(
        f"{base}/analysis-runs", json={"mode": "custom", "overrides": {"tiles": [9, 9]}}
    )
    assert custom.status_code == 422


def test_switching_back_to_a_mode_restores_its_rows(quick: tuple[Any, Any, int]) -> None:
    """Quick → Thorough → Quick: Quick's artifacts still exist, but the rows were
    replaced by Thorough's, so the stages run again instead of keeping Thorough's."""
    project, control, _ = quick
    with project.db.session() as s:
        assert {m.cols for m in s.scalars(select(Mosaic))} == {4}, "Thorough ran last"
    job = submit_analysis(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, "quick"
    )
    assert run_job(control, job, timeout=1800) == "done"
    with project.db.session() as s:
        methods = set(s.scalars(select(Shot.method).where(Shot.method != "photo")))
        sheets = {(m.cols, m.rows) for m in s.scalars(select(Mosaic))}
    assert methods <= {"threshold", "forced"}
    assert sheets == {(6, 4)}
