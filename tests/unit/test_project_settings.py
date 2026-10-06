"""Project settings and the S9 ready-to-browse rule (ADR 0041)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.core.modes import resolve
from mosaic.library.progress_view import ready_to_browse
from mosaic.storage import project_settings as ps
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import init_project


def test_settings_store_validate_and_report_their_source(tmp_path: Path) -> None:
    control = ControlDB()
    me = control.local_principal
    project = init_project(control, me, tmp_path)
    cfg = ConfigService(control)
    with project.db.session() as s:
        eff = ps.effective(s, cfg, me)
    assert eff["analysis.mode"] == {"value": "balanced", "source": "default"}
    assert eff["analysis.sample_interval"] == {"value": "3", "source": "mode"}
    assert eff["analysis.cost_limit_usd"]["source"] == "default"
    with project.write() as s:
        ps.patch(s, {"analysis.sample_interval": 2, "analysis.tiles": [5, 4], "ai.send_gps": True})
    with project.db.session() as s:
        eff = ps.effective(s, cfg, me, "thorough")
        assert eff["analysis.sample_interval"] == {"value": "2", "source": "project"}
        assert eff["analysis.forced_max_shot"] == {"value": "30", "source": "mode"}
        assert eff["ai.send_gps"] == {"value": True, "source": "project"}
        overrides = ps.mode_overrides(s)
    config = ps.run_config("thorough", overrides)
    assert config.name == "custom"
    assert config.l3, "a custom run keeps its preset's levels"
    assert config.tiles == (5, 4)
    assert ps.run_config("quick", {}) == resolve("quick")
    for bad in (
        {"analysis.tiles": [1, 9]},
        {"analysis.sample_interval": "0"},
        {"analysis.mode": "custom"},
        {"analysis.cost_limit_usd": True},
        {"nope": 1},
    ):
        with project.write() as s, pytest.raises(ps.ProjectSettingError):
            ps.patch(s, bad)
    with project.write() as s:
        ps.patch(s, {"analysis.sample_interval": None})
    with project.db.session() as s:
        assert "analysis.sample_interval" not in ps.stored(s)
    project.close()


def test_ready_to_browse_waits_for_l0_and_per_asset_l1_only() -> None:
    levels = {"proxy": 1, "visual": 1, "audio": 1, "vision": 2}
    assert not ready_to_browse({"scan": {"done": 1}}, levels), "the scan has not spawned work yet"
    counts = {
        "scan": {"done": 1},
        "probe": {"done": 3},
        "proxy": {"done": 3},
        "visual": {"done": 2, "running": 1},
        "vision": {"pending": 5},
    }
    assert not ready_to_browse(counts, levels)
    counts["visual"] = {"done": 2, "failed": 1}
    assert ready_to_browse(counts, levels), "L2 work and failed clips do not hold it back"


def test_step_states_keep_cancelled_work_apart_from_failure() -> None:
    from mosaic.library.progress_view import step_state

    assert step_state(4, 0, 0, 4, "running") == "done"
    assert step_state(2, 0, 1, 4, "running") == "running"
    assert step_state(0, 0, 0, 4, "running") == "pending"
    assert step_state(2, 0, 0, 4, "paused") == "paused"
    assert step_state(2, 0, 0, 4, "paused_cost_limit") == "paused"
    assert step_state(2, 0, 0, 4, "cancelled") == "pending", "work kept, Resume (S9)"
    assert step_state(2, 1, 0, 4, "failed") == "failed"


def test_failures_show_catalog_phrases_never_tool_output(tmp_path: Path) -> None:
    import json

    from sqlalchemy import update

    from mosaic.jobs.model import JobSpec, TaskSpec
    from mosaic.jobs.store import JobStore
    from mosaic.library.progress_view import analysis_progress
    from mosaic.storage.models_control import Task

    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    store = JobStore(control.db)
    raw = [
        "ffmpeg: [h264 @ 0x7f] /Users/me/trip/GX01.MP4: Invalid data found when processing",
        'Traceback (most recent call last):\n  File "/opt/x.py", line 3\nPermanentError: boom',
        "subprocess.TimeoutExpired: Command '['ffprobe', '/secret/a.mov']' timed out after 30 s",
    ]
    job = store.create_job(
        control.local_principal,
        JobSpec(
            project.id,
            "analysis",
            tasks=[TaskSpec("x", "proxy", params={"asset_id": i}) for i in range(1, 4)],
        ),
    )
    with control.db.session() as cs:
        for i, err in enumerate(raw, start=1):
            cs.execute(
                update(Task)
                .where(Task.job_id == job, Task.params["asset_id"].as_integer() == i)
                .values(status="failed", error=err)
            )
        row = store.job(job)
        assert row is not None
        with project.db.session() as s:
            out = analysis_progress(cs, s, row)
    text = json.dumps(out)
    assert out["failures"]["count"] == 3
    assert sorted(f["reason"] for f in out["failures"]["items"]) == [
        "couldn't be processed",
        "couldn't be read",
        "timed out",
    ]
    for leak in ("ffmpeg", "Traceback", "/Users/me", "/secret", "0x7f", "Invalid data"):
        assert leak not in text, leak
    project.close()


def test_a_custom_run_is_estimated_at_its_presets_speed() -> None:
    from fractions import Fraction

    from mosaic.library.estimate import _local_seconds

    cfg = ConfigService(ControlDB())  # no benchmark: the default speed factors
    custom = ps.run_config("thorough", {"tiles": (5, 4)})
    assert custom.preset == "thorough"
    same = _local_seconds(cfg, custom, Fraction(600), 10, 1)
    assert same == _local_seconds(cfg, resolve("thorough"), Fraction(600), 10, 1)
    assert same[1] == "default"
