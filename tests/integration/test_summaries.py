"""Summaries on the analyzed synthetic corpus (M1 step 5): written by the analysis,
unchanged inputs ask nothing, and a context change re-runs summaries only."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.library.summaries import submit_summaries
from mosaic.storage.models_project import Asset, Summary
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


def test_analysis_writes_every_level(analyzed_session: Any) -> None:
    project, _ = analyzed_session
    with project.db.session() as s:
        rows = list(s.scalars(select(Summary)))
        videos = s.scalar(
            select(func.count(Asset.id)).where(Asset.kind == "video", Asset.status == "ok")
        )
    levels = {r.level for r in rows}
    assert levels == {"shot", "scene", "day", "trip"}
    scenes = [r for r in rows if r.level == "scene"]
    assert 0 < len(scenes) <= (videos or 0)
    for r in scenes:
        assert r.text
        assert isinstance(r.data["span"]["ticks"], int)
    days = [r for r in rows if r.level == "day"]
    assert [d.ref for d in days] == [0], "the synthetic corpus has no capture dates"
    trip = next(r for r in rows if r.level == "trip")
    assert trip.text.startswith("Summary of the whole trip")


def test_context_change_reruns_summaries_only(analyzed_session: Any) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, control = analyzed_session
    executor = LocalExecutor(JobStore(control.db))
    before = len(fake.CALLS)
    job = submit_summaries(executor, control.local_principal, project)
    assert run_job(control, job, timeout=300) == "done"
    assert fake.CALLS[before:] == [], "unchanged inputs and context: nothing is asked"

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    base = f"/api/projects/{project.id}"
    old = client.get(f"{base}/trip-context").json()
    try:
        r = client.put(f"{base}/trip-context", json={"trip_name": "Summary test"})
        assert r.status_code == 200, r.text
        job = r.json()["summaries_job"]
        before = len(fake.CALLS)
        assert run_job(control, job, timeout=300) == "done"
        assert fake.CALLS[before:] == ["summary", "summary"], "one day and the trip, nothing else"
        tasks = JobStore(control.db).tasks(job)
        assert [t.kind for t in tasks] == ["library.summaries"]
        got = client.get(f"{base}/summaries").json()["items"]
        assert [i["level"] for i in got] == ["day", "trip"]
        assert all(set(i["highlights"]) for i in got)
    finally:
        old.pop("revision", None)
        r = client.put(f"{base}/trip-context", json=old)
        assert run_job(control, r.json()["summaries_job"], timeout=300) == "done"


def test_shot_summaries_are_paged(analyzed_session: Any) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, control = analyzed_session
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    url = f"/api/projects/{project.id}/summaries"
    first = client.get(url, params={"level": "shot", "limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["next_after_ref"] == first["items"][-1]["ref"]
    rest = client.get(
        url, params={"level": "shot", "limit": 1000, "after_ref": first["next_after_ref"]}
    ).json()
    refs = [i["ref"] for i in first["items"] + rest["items"]]
    assert refs == sorted(set(refs))
    assert rest["next_after_ref"] is None
    with project.db.session() as s:
        total = s.scalar(select(func.count(Summary.id)).where(Summary.level == "shot"))
    assert len(refs) == total
    assert client.get(url, params={"level": "week"}).status_code == 422
