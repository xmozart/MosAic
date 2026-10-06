"""S8 and S9 endpoints: project settings, estimates with Advanced overrides, progress
(ADR 0041)."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _client(control: Any) -> Any:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


def test_progress_of_a_finished_analysis(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    r = client.get(f"/api/projects/{project.id}/analysis/progress")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["kind"] == "analysis"
    assert p["ready_to_browse"] is True
    keys = [st["key"] for st in p["steps"]]
    assert keys[0] == "look"
    assert {"previews", "shots", "frames", "scenes", "library"} <= set(keys)
    assert all(st["state"] == "done" for st in p["steps"])
    notes = {st["key"]: st["note"] for st in p["steps"]}
    assert notes["shots"].endswith(" shots")
    assert " → " in notes["frames"]
    assert p["clips"]["done"] == p["clips"]["total"] > 0
    live = p["live"]
    assert live is not None, "the fake vision adapter described sheets"
    assert live["tiles"] > 0
    assert live["file"]
    sheet = client.get(f"/api/media/{project.id}/mosaic/{live['mosaic_id']}")
    assert sheet.status_code == 200
    assert sheet.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/media/{project.id}/mosaic/999999").status_code == 404
    assert p["failures"]["count"] == len(p["failures"]["items"])
    for f in p["failures"]["items"]:
        assert f["reason"] in ("timed out", "couldn't be read", "couldn't be processed")
    again = client.get(f"/api/projects/{project.id}/analysis/progress", params={"job": p["job_id"]})
    assert again.json()["job_id"] == p["job_id"]
    assert (
        client.get(
            f"/api/projects/{project.id}/analysis/progress", params={"job": 999999}
        ).status_code
        == 404
    )


def test_settings_and_estimates_follow_advanced_overrides(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    base = f"/api/projects/{project.id}"
    eff = client.get(f"{base}/settings", params={"mode": "quick"}).json()["settings"]
    assert eff["analysis.sample_interval"] == {"value": "6", "source": "mode"}
    plain = client.get(f"{base}/analysis/estimate", params={"mode": "balanced"}).json()
    denser = client.get(
        f"{base}/analysis/estimate",
        params={"mode": "balanced", "overrides": '{"analysis.tiles": [2, 2]}'},
    ).json()
    assert denser["l2_calls"] > plain["l2_calls"], "smaller sheets need more vision calls"
    for bad in ('{"x": 1}', '{"analysis.sample_interval": 0.001}', "[1]", "{"):
        r = client.get(f"{base}/analysis/estimate", params={"mode": "balanced", "overrides": bad})
        assert r.status_code == 422, bad
    try:
        r = client.patch(f"{base}/settings", json={"values": {"analysis.tiles": [2, 2]}})
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["analysis.tiles"] == {"value": [2, 2], "source": "project"}
        saved = client.get(f"{base}/analysis/estimate", params={"mode": "balanced"}).json()
        assert saved["l2_calls"] == denser["l2_calls"], "stored overrides apply to estimates"
        bad = client.patch(f"{base}/settings", json={"values": {"analysis.tiles": [1, 1]}})
        assert bad.status_code == 422
    finally:
        client.patch(f"{base}/settings", json={"values": {"analysis.tiles": None}})
    assert "analysis.tiles" not in client.get(f"{base}/settings").json()["settings"] or (
        client.get(f"{base}/settings").json()["settings"]["analysis.tiles"]["source"] == "mode"
    )


def test_a_preset_run_carries_the_project_overrides(corpus_dir: Any, tmp_path: Any) -> None:
    import shutil

    from mosaic.jobs.store import JobStore
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project

    trip = tmp_path / "trip"
    trip.mkdir()
    shutil.copy2(corpus_dir / "speech.mp4", trip / "speech.mp4")
    control = ControlDB()
    project = init_project(control, control.local_principal, trip)
    pid = project.id
    project.close()
    client = _client(control)
    client.patch(
        f"/api/projects/{pid}/settings",
        json={"values": {"analysis.sample_interval": 2, "analysis.cost_limit_usd": 3.5}},
    )
    r = client.post(f"/api/projects/{pid}/analysis-runs", json={"mode": "thorough"})
    assert r.status_code == 202, r.text
    row = JobStore(control.db).job(r.json()["job_id"])
    assert row is not None
    assert row.cost_limit_usd == 3.5, "the project's cost limit"
    params = row.params
    assert params["preset"] == "thorough"
    mode = params["mode_config"]
    assert mode["name"] == "custom"
    assert mode["sample_interval"] == "2"
    assert mode["l3"] is True
    client.post(f"/api/jobs/{r.json()['job_id']}/cancel")


def test_progress_of_a_deepening_job_carries_its_scope(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    r = client.post(
        f"/api/projects/{project.id}/analysis-runs",
        json={"mode": "thorough", "scope": {"kind": "trip"}},
    )
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    if job is None:
        pytest.fail("a Balanced corpus has L3 candidates to deepen")
    try:
        p = client.get(f"/api/projects/{project.id}/analysis/progress", params={"job": job}).json()
        assert p["kind"] == "deepen"
        assert p["mode"] == "thorough"
        assert p["deepen"] == {"target": "thorough", "days": [], "segment_ids": []}
    finally:
        client.post(f"/api/jobs/{job}/cancel")
