"""Embeddings, segments, usable_range and similarity groups (M0 step 8)."""

from __future__ import annotations

import itertools
import json
import os
from fractions import Fraction

import numpy as np
import pytest
from sqlalchemy import select

from mosaic.ai.adapters.siglip_onnx.embedder import DIM
from mosaic.ai.adapters.siglip_onnx.embedder import model_id as _model_id
from mosaic.storage import sqlite_vec_index
from mosaic.storage.models_project import (
    Asset,
    Embedding,
    MediaFile,
    SampleFrame,
    Segment,
    Shot,
    SimilarityGroup,
)
from mosaic.storage.projects import Project

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def analyzed(analyzed_corpus: Project) -> Project:
    return analyzed_corpus


def _asset(project: Project, name: str) -> Asset:
    with project.db.session() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == name))
        assert mf is not None
        a = s.get(Asset, mf.asset_id)
        assert a is not None
        return a


def test_segments_tile_every_shot(analyzed: Project) -> None:
    with analyzed.db.session() as s:
        shots = list(s.scalars(select(Shot)))
        segs = list(s.scalars(select(Segment).order_by(Segment.asset_id, Segment.index)))
    assert segs
    by_shot: dict[int, list[Segment]] = {}
    for g in segs:
        by_shot.setdefault(g.shot_id, []).append(g)
        assert g.start_ticks <= g.usable_start_ticks <= g.usable_end_ticks <= g.end_ticks
    for sh in shots:
        pieces = sorted(by_shot[sh.id], key=lambda g: g.start_ticks)
        assert pieces[0].start_ticks == sh.start_ticks
        assert pieces[-1].end_ticks == sh.end_ticks
        for a, b in itertools.pairwise(pieces):
            assert a.end_ticks == b.start_ticks, "segments must not cross or gap a shot"


def test_wobble_is_trimmed_from_usable_range(analyzed: Project) -> None:
    asset = _asset(analyzed, "wobble.mp4")
    tb = Fraction(asset.tb)
    case = next(
        c
        for c in json.loads((analyzed.root / "manifest.json").read_text())["cases"]
        if c["name"] == "wobble"
    )
    wobble = Fraction(case["wobble_frames"]) / Fraction(case["rate"])
    with analyzed.db.session() as s:
        first = s.scalar(
            select(Segment)
            .where(Segment.asset_id == asset.id)
            .order_by(Segment.start_ticks)
            .limit(1)
        )
    assert first is not None
    assert abs(first.usable_start_ticks * tb - wobble) <= Fraction(1, 2)
    steady = _asset(analyzed, "A001_basic.mp4")
    with analyzed.db.session() as s:
        segs = list(s.scalars(select(Segment).where(Segment.asset_id == steady.id)))
    assert all(g.usable_start_ticks == g.start_ticks for g in segs)


def test_embeddings_exist_and_index_finds_duplicates(analyzed: Project) -> None:
    model = model_id()
    with analyzed.db.session() as s:
        kept = list(s.scalars(select(SampleFrame.id).where(SampleFrame.image_key.is_not(None))))
        sample_vecs = set(
            s.scalars(
                select(Embedding.owner_id).where(
                    Embedding.owner_kind == "sample", Embedding.model == model
                )
            )
        )
        segs = list(s.scalars(select(Segment)))
        seg_vecs = {
            e.owner_id: e
            for e in s.scalars(
                # Photos' one-frame segments have their own kind and index (ADR 0025).
                select(Embedding).where(
                    Embedding.owner_kind.in_(("segment", "photo_segment")),
                    Embedding.model == model,
                )
            )
        }
        assert set(kept) <= sample_vecs
        assert {g.id for g in segs} == set(seg_vecs)
        a002, a003 = _asset(analyzed, "A002_basic.mp4"), _asset(analyzed, "A003_dup.mp4")
        index = sqlite_vec_index.index_name(model, DIM, "segment")
        dup_ids = {g.id for g in segs if g.asset_id == a003.id}
        for g in (g for g in segs if g.asset_id == a002.id):
            vec = np.frombuffer(seg_vecs[g.id].vector, dtype=np.float32)
            hits = [h for h in sqlite_vec_index.knn(s, index, vec, 3) if h[0] != seg_vecs[g.id].id]
            owner = s.get(Embedding, hits[0][0])
            assert owner is not None
            assert owner.owner_id in dup_ids, "nearest neighbour must be the identical clip"


def test_duplicates_share_a_similarity_group_with_one_best(analyzed: Project) -> None:
    a002, a003 = _asset(analyzed, "A002_basic.mp4"), _asset(analyzed, "A003_dup.mp4")
    with analyzed.db.session() as s:
        segs = list(s.scalars(select(Segment)))
        groups = list(s.scalars(select(SimilarityGroup)))
    by_index = {(g.asset_id, g.index): g for g in segs}
    for (asset_id, idx), g in by_index.items():
        if asset_id == a002.id:
            twin = by_index[(a003.id, idx)]
            assert g.similarity_group_id is not None
            assert g.similarity_group_id == twin.similarity_group_id
    for grp in groups:
        members = [g for g in segs if g.similarity_group_id == grp.id]
        assert len(members) == grp.size >= 2
        best = [g for g in members if g.group_best]
        assert [b.id for b in best] == [grp.best_segment_id]
        assert best[0].quality == max(m.quality for m in members)


def test_rerunning_visual_rebuilds_downstream_without_orphans(
    corpus_dir,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """A changed visual key re-runs shots and samples on an analyzed asset: segments and
    embeddings built from the old samples are removed first (foreign keys hold)."""
    import shutil

    from sqlalchemy import text

    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media import visual
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.support.runner import run_job

    root = tmp_path / "trip"
    root.mkdir()
    shutil.copy(corpus_dir / "A001_basic.mp4", root / "A001_basic.mp4")
    control = ControlDB()
    project = init_project(control, control.local_principal, root)
    ex = LocalExecutor(JobStore(control.db))
    assert run_job(control, submit_analysis(ex, control.local_principal, project)) == "done"
    monkeypatch.setattr(visual, "VISUAL_VERSION", "visual/rerun-test")
    assert run_job(control, submit_analysis(ex, control.local_principal, project)) == "done"
    model = model_id()
    with project.db.session() as s:
        samples = set(s.scalars(select(SampleFrame.id)))
        segments = set(s.scalars(select(Segment.id)))
        owners = list(s.execute(select(Embedding.owner_kind, Embedding.owner_id, Embedding.id)))
        assert segments
        for kind, owner, _ in owners:
            assert owner in (samples if kind == "sample" else segments), (kind, owner)
        for kind in ("sample", "segment"):
            name = sqlite_vec_index.index_name(model, DIM, kind)
            rowids = set(s.scalars(text(f"SELECT rowid FROM {name}")))
            assert rowids == {e for k, _, e in owners if k == kind}, kind
    project.close()


def model_id() -> str:
    return _model_id(os.environ["MOSAIC_EMBED_VARIANT"])
