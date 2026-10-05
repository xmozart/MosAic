"""Mosaics, vision observations and dispositions on the synthetic corpus (M0 step 9c)."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.library import segments as segments_module
from mosaic.library.mosaics import PER_SEGMENT
from mosaic.media.pipeline import submit_analysis
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import (
    Asset,
    Disposition,
    MediaFile,
    Mosaic,
    MosaicTile,
    Provenance,
    Segment,
    VisualObservation,
)
from mosaic.storage.projects import Project, init_project
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


def _asset_id(project: Project, name: str) -> int:
    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == name))
    assert aid is not None
    return aid


def test_mosaics_cover_every_segment_once(analyzed_corpus: Project) -> None:
    project = analyzed_corpus
    with project.db.session() as s:
        segments = {g.id: g for g in s.scalars(select(Segment))}
        tiles = list(s.scalars(select(MosaicTile)))
        mosaics = {m.id: m for m in s.scalars(select(Mosaic))}
        tbs = {aid: tb for aid, tb in s.execute(select(Asset.id, Asset.tb))}
    assert mosaics
    sheets_of: dict[int, set[int]] = {}
    per_segment: dict[int, int] = {}
    for t in tiles:
        g = segments[t.segment_id]
        m = mosaics[t.mosaic_id]
        assert m.asset_id == g.asset_id, "tiles come from one asset per sheet"
        sheets_of.setdefault(g.id, set()).add(t.mosaic_id)
        per_segment[g.id] = per_segment.get(g.id, 0) + 1
    assert set(sheets_of) == set(segments), "every segment appears on a sheet"
    assert all(len(v) == 1 for v in sheets_of.values()), "a segment is never split"
    assert max(per_segment.values()) <= PER_SEGMENT
    for t in tiles:
        g = segments[t.segment_id]
        # A tile lies in its segment, except the single nearest-sample fallback tile.
        assert g.start_ticks <= t.ticks < g.end_ticks or per_segment[g.id] == 1
    for m in mosaics.values():
        count = sum(1 for t in tiles if t.mosaic_id == m.id)
        assert 1 <= count <= m.cols * m.rows
        with Image.open(io.BytesIO(project.artifacts.get_bytes("mosaic", m.image_key))) as im:
            assert im.width <= 1568
            assert im.height <= 1568
        sidecar = project.artifacts.get_json("mosaic", f"{m.image_key}-tiles")
        rows = sorted((t for t in tiles if t.mosaic_id == m.id), key=lambda t: t.tile)
        assert [x["tile"] for x in sidecar["tiles"]] == [f"T{t.tile:02d}" for t in rows]
        assert [x["time"] for x in sidecar["tiles"]] == [
            {"ticks": t.ticks, "tb": tbs[m.asset_id]} for t in rows
        ]


def test_every_segment_has_one_observation(analyzed_corpus: Project) -> None:
    with analyzed_corpus.db.session() as s:
        seg_ids = set(s.scalars(select(Segment.id)))
        observations = list(s.scalars(select(VisualObservation)))
        tiles = {(t.segment_id, t.sample_id, t.ticks) for t in s.scalars(select(MosaicTile))}
        calls = s.scalar(select(func.count(Provenance.id)).where(Provenance.kind == "ai.vision"))
        sheets = s.scalar(select(func.count(Mosaic.id)))
    assert {o.segment_id for o in observations} == seg_ids
    assert len(observations) == len(seg_ids)
    assert calls == sheets, "one vision call per sheet"
    for o in observations:
        best = o.data["best_frame"]
        assert (o.segment_id, best["sample_id"], best["time"]["ticks"]) in tiles
        assert o.data["interest"] in ("low", "medium", "high")


def test_dispositions_reject_accidental_and_pocket(analyzed_corpus: Project) -> None:
    project = analyzed_corpus
    with project.db.session() as s:
        rows = list(s.scalars(select(Disposition)))
        seg_asset = {sid: aid for sid, aid in s.execute(select(Segment.id, Segment.asset_id))}
    assert {r.source for r in rows} == {"ai"}
    assert sorted(r.segment_id for r in rows if r.segment_id) == sorted(seg_asset)

    def by_file(name: str) -> list[Disposition]:
        aid = _asset_id(project, name)
        return [r for r in rows if r.asset_id == aid]

    accidental = by_file("accidental.mp4")
    assert accidental
    assert all(r.status == "REJECT" for r in accidental)
    assert all(any(x["code"] == "accidental_recording" for x in r.reasons) for r in accidental)
    pocket = by_file("pocket.mp4")
    assert pocket
    assert all(r.status == "REJECT" for r in pocket)
    assert all({x["code"] for x in r.reasons} & {"obstructed", "black_frames"} for r in pocket)
    assert any(r.status == "USE" for r in by_file("A001_basic.mp4"))


def test_vision_without_a_key_is_skipped_then_cached(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No key: analysis completes with vision skipped and rule-only dispositions. With a
    provider, vision runs once; re-analysis makes zero AI calls (M0 acceptance 5)."""
    root = tmp_path / "trip"
    root.mkdir()
    for name in ("A001_basic.mp4", "accidental.mp4"):
        shutil.copy2(corpus_dir / name, root / name)
    control = ControlDB()
    me = control.local_principal
    project = init_project(control, me, root)
    executor = LocalExecutor(JobStore(control.db))
    store = JobStore(control.db)

    job = submit_analysis(executor, me, project)
    assert run_job(control, job, timeout=900) == "done"
    vision = [t for t in store.tasks(job) if t.kind == "library.vision"]
    assert vision
    assert all(t.status == "skipped" for t in vision)
    assert all("set-key --provider anthropic" in (t.error or "") for t in vision)
    with project.db.session() as s:
        assert s.scalar(select(func.count(VisualObservation.id))) == 0
        assert s.scalar(select(func.count(Disposition.id))) == s.scalar(
            select(func.count(Segment.id))
        )

    ConfigService(control).set_provider(me, "vision", "fake", "fake")
    job = submit_analysis(executor, me, project)
    assert run_job(control, job, timeout=900) == "done"
    with project.db.session() as s:
        observed = s.scalar(select(func.count(VisualObservation.id)))
        first = {o.segment_id: o.data for o in s.scalars(select(VisualObservation))}
    assert observed
    before = len(fake.CALLS)
    job = submit_analysis(executor, me, project)
    assert run_job(control, job, timeout=900) == "done"
    assert len(fake.CALLS) == before, "re-analysis must not call the provider again"
    with project.db.session() as s:
        assert {o.segment_id: o.data for o in s.scalars(select(VisualObservation))} == first

    # Segments rebuilt (purging mosaics and observations, SQLite reusing the row ids):
    # mosaics and observations must come back, answered from the AI cache.
    monkeypatch.setattr(segments_module, "SEGMENT_VERSION", "segments/2-rebuilt")
    job = submit_analysis(executor, me, project)
    assert run_job(control, job, timeout=900) == "done"
    assert len(fake.CALLS) == before, "identical sheets are answered from the cache"
    with project.db.session() as s:
        seg_ids = set(s.scalars(select(Segment.id)))
        rebuilt = {o.segment_id: o.data for o in s.scalars(select(VisualObservation))}
        ai_rows = s.scalar(select(func.count(Disposition.id)).where(Disposition.source == "ai"))
    assert set(rebuilt) == seg_ids
    assert len(rebuilt) == len(first)
    assert ai_rows == len(seg_ids)
    project.close()
