"""L3 deep review on the analyzed synthetic corpus (M1 step 2; M1 acceptance 5 and 7)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.library.review import plan_deepen, submit_deepen
from mosaic.storage.models_project import DeepReview, Disposition, Provenance
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


def test_deep_review_one_call_per_candidate_then_cached(analyzed_session: Any) -> None:
    project, control = analyzed_session
    with project.db.session() as s:
        plan, _ = plan_deepen(s)
    candidates = sum(len(v) for v in plan.values())
    assert candidates > 0
    executor = LocalExecutor(JobStore(control.db))
    before = fake.CALLS.count("review")
    job, count, _ = submit_deepen(executor, control.local_principal, project)
    assert job is not None
    assert count == candidates
    assert run_job(control, job, timeout=900) == "done"
    assert fake.CALLS.count("review") - before == candidates, "one AI call per candidate"
    with project.db.session() as s:
        reviewed = s.scalar(select(func.count(DeepReview.id)))
        calls = s.scalar(select(func.count(Provenance.id)).where(Provenance.kind == "ai.reviewer"))
        rejected = set(
            s.scalars(select(Disposition.segment_id).where(Disposition.status == "REJECT"))
        )
        rows = list(s.scalars(select(DeepReview)))
    assert reviewed == candidates
    assert calls == candidates
    assert not {r.segment_id for r in rows} & rejected, "REJECT segments are never reviewed"
    for r in rows:
        assert r.data["description"].startswith("Reviewed at full resolution")
        assert isinstance(r.data["best_frame"]["time"]["ticks"], int)
    # Deepening again: every candidate's stored key matches, so nothing is decoded or asked.
    before = fake.CALLS.count("review")
    job, _, _ = submit_deepen(executor, control.local_principal, project)
    assert job is not None
    assert run_job(control, job, timeout=900) == "done"
    assert fake.CALLS.count("review") == before
    store = JobStore(control.db)
    unchanged = sum(
        t.result.get("unchanged", 0) for t in store.tasks(job) if t.kind == "library.review"
    )
    assert unchanged == candidates


def test_l3_supersedes_l2_in_retrieval(analyzed_session: Any) -> None:
    from fractions import Fraction

    from mosaic.editing.retrieval import retrieve

    project, _ = analyzed_session
    with project.db.session() as s:
        reviewed = set(s.scalars(select(DeepReview.segment_id)))
        cands, _ = retrieve(s, Fraction(1), Fraction(30))
    assert reviewed
    for c in cands:
        if c.segment_id in reviewed:
            assert c.obs["description"].startswith("Reviewed at full resolution")


def _until_paused(control: Any, job: int, timeout: float = 120) -> None:
    """Run a worker until the job pauses at its cost limit (a non-terminal state)."""
    import threading
    import time

    from mosaic.jobs.worker import Worker

    store = JobStore(control.db)
    worker = Worker(control, slots={"cpu": 2, "io": 1, "gpu_encode": 1, "ai_api": 1})
    th = threading.Thread(target=worker.run, daemon=True)
    th.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            j = store.job(job)
            if j is not None and j.status in ("paused_cost_limit", "done", "failed"):
                return
            time.sleep(0.05)
    finally:
        worker.stop.set()
        th.join(timeout=30)


def test_cost_limit_pause_then_raise_and_resume(
    analyzed_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, control = analyzed_session
    store = JobStore(control.db)
    with project.db.session() as s:
        plan, _ = plan_deepen(s)
    seg_ids = [sid for ids in plan.values() for sid in ids][:3]
    assert len(seg_ids) == 3
    monkeypatch.setenv("MOSAIC_FAKE_COST_USD", "0.3")
    from mosaic.ai import client as ai_client

    # Fresh (uncached) answers so the calls are priced and the limit is reached.
    monkeypatch.setattr(ai_client, "AI_CACHE_VERSION", "ai-cache/test-pause")
    with project.write() as s:  # make them due again (keys would match otherwise)
        s.query(DeepReview).filter(DeepReview.segment_id.in_(seg_ids)).delete()
    job, count, _ = submit_deepen(
        LocalExecutor(store),
        control.local_principal,
        project,
        segment_ids=seg_ids,
        cost_limit_usd=0.5,
    )
    assert job is not None
    assert count == 3
    _until_paused(control, job)
    paused = store.job(job)
    assert paused is not None
    assert paused.status == "paused_cost_limit"
    assert 0 < paused.cost_usd <= 0.5
    store.set_cost_limit(job, 5.0)
    LocalExecutor(store).resume(control.local_principal, job)
    assert run_job(control, job, timeout=300) == "done"
    done = store.job(job)
    assert done is not None
    assert done.cost_usd == pytest.approx(0.9)


def test_day_scope_matches_the_editor(tmp_path: Any) -> None:
    """Two recordings on two days (one with a UTC offset, one without): --day selects
    exactly that day's candidates, numbered as the editor numbers them. (The synthetic
    corpus has no capture dates.)"""
    from fractions import Fraction

    from mosaic.core.clock import now_iso
    from mosaic.editing.retrieval import capture_dates, trip_day
    from mosaic.storage import provenance
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_project import Asset, Segment, Shot
    from mosaic.storage.projects import init_project

    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    by_day: dict[int, set[int]] = {}
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        for n, when in enumerate(("2026-09-05T23:59:30-04:00", "2026-09-06T10:00:00")):
            a = Asset(
                kind="video",
                status="ok",
                profile="gopro",
                group_key=f"g{n}",
                tb="1/1000",
                capture_time=when,
                provenance_id=prov,
                created_at=now_iso(),
            )
            s.add(a)
            s.flush()
            sh = Shot(
                asset_id=a.id,
                index=0,
                start_ticks=0,
                end_ticks=60_000,
                method="adaptive",
                provenance_id=prov,
            )
            s.add(sh)
            s.flush()
            for k in range(3):  # 0–20 s, 20–40 s, 40–60 s
                g = Segment(
                    asset_id=a.id,
                    shot_id=sh.id,
                    index=k,
                    start_ticks=k * 20_000,
                    end_ticks=(k + 1) * 20_000,
                    usable_start_ticks=k * 20_000,
                    usable_end_ticks=(k + 1) * 20_000,
                    provenance_id=prov,
                )
                s.add(g)
                s.flush()
        s.flush()
        assets = list(s.query(Asset).order_by(Asset.id))
        first_day = min(capture_dates(assets).values())
        for g in s.query(Segment):
            a = next(x for x in assets if x.id == g.asset_id)
            day = trip_day(a.capture_time, Fraction(g.start_ticks, 1000), first_day)
            by_day.setdefault(day, set()).add(g.id)
    # The first recording crosses midnight: its 40–60 s segment is on day 2. The second
    # recording's time has no UTC offset (naive), mixed with the offset-aware one.
    assert {d: len(v) for d, v in by_day.items()} == {1: 2, 2: 4}
    with project.db.session() as s:
        for day, expected in by_day.items():
            plan, dropped = plan_deepen(s, day=day)
            got = {sid for ids in plan.values() for sid in ids}
            assert got == expected, (day, got, expected)
            assert dropped == []
        plan, dropped = plan_deepen(s, segment_ids=[999_999])
    assert plan == {}
    assert dropped == [999_999]
    project.close()


def test_undecodable_frames_skip_the_clip(
    analyzed_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.library import review
    from mosaic.media.ffmpeg.run import FFmpegError

    project, control = analyzed_session
    with project.db.session() as s:
        plan, _ = plan_deepen(s)
    _, ids = next(iter(plan.items()))
    with project.write() as s:
        s.query(DeepReview).filter(DeepReview.segment_id.in_(ids)).delete()

    def broken(*_a: Any, **_k: Any) -> Any:
        raise FFmpegError("still", [], 1, "invalid data")

    monkeypatch.setattr(review, "run", broken)
    job, count, _ = submit_deepen(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, segment_ids=ids
    )
    assert job is not None
    assert run_job(control, job, timeout=300) == "done", "bad media never fails the task"
    task = next(t for t in JobStore(control.db).tasks(job) if t.kind == "library.review")
    assert len(task.result["skipped"]) == count
    assert "frame not decodable" in task.result["skipped"][0]


def test_resume_api_validates_the_new_limit(analyzed_session: Any) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec

    project, control = analyzed_session
    store = JobStore(control.db)
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project.id,
            "deepen",
            cost_limit_usd=0.5,
            tasks=[TaskSpec("x", "s", resource_class=ResourceClass.AI_API)],
        ),
    )
    store.reserve_cost(job, 0.4)
    store.pause(job, cost_limit=True)
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    assert client.post(f"/api/jobs/{job}/resume", json={"cost_limit_usd": 0.4}).status_code == 422
    assert client.post(f"/api/jobs/{job}/cancel", json={"cost_limit_usd": 9}).status_code == 422
    ok = client.post(f"/api/jobs/{job}/resume", json={"cost_limit_usd": 2.0})
    assert ok.status_code == 200
    assert store.job(job).cost_limit_usd == 2.0  # type: ignore[union-attr]
    store.pause(job)
    assert client.post(f"/api/jobs/{job}/resume").status_code == 200  # no body: plain resume
    store.cancel(job)
