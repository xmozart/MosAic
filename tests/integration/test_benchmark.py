"""Hardware benchmark → estimates (M1 step 12, ADR 0030)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def test_measure_times_the_real_stages(tmp_path: Path) -> None:
    from mosaic.media.benchmark import measure

    calls: list[int] = []

    def embed(images: Any) -> None:
        calls.append(len(images))

    result = measure(tmp_path, embed)
    per = result["ms_per_minute"]
    assert set(per) == {"lrf_or_540", "720", "analysis"}
    assert all(isinstance(v, int) and v > 0 for v in per.values())
    assert isinstance(result["embed_ms_per_image"], int)
    assert calls == [1, 16], "one warm-up, then the timed batch"


def test_benchmark_job_runs_once_per_computer(tmp_path: Path) -> None:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media import benchmark
    from mosaic.media.pipeline import needs_benchmark, submit_benchmark
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.support.runner import run_job

    control = ControlDB()
    ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
    (tmp_path / "trip").mkdir()
    project = init_project(control, control.local_principal, tmp_path / "trip")
    store = JobStore(control.db)
    assert needs_benchmark(control)
    job = submit_benchmark(LocalExecutor(store), control.local_principal, project)
    assert run_job(control, job, timeout=300) == "done"
    found = benchmark.latest(control)
    assert found is not None
    assert found.ms_per_minute("720")
    assert not needs_benchmark(control)
    again = submit_benchmark(LocalExecutor(store), control.local_principal, project)
    assert run_job(control, again, timeout=120) == "done"
    assert "skipped_existing" in {e.event for e in store.events(again)}
    project.close()


def test_estimate_uses_the_benchmark(tmp_path: Path) -> None:
    from mosaic.core.modes import resolve
    from mosaic.jobs.worker import configured_slots
    from mosaic.library.estimate import SPEED, _local_seconds
    from mosaic.media import benchmark, hardware
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    config = ConfigService(control)
    mode = resolve("balanced")
    footage = Fraction(600)  # ten minutes in four clips
    local, basis = _local_seconds(config, mode, footage, 200, 4)
    assert basis == "default"
    assert local == footage * SPEED["balanced"]
    benchmark.save(
        control,
        hardware.probe(),
        {
            "ms_per_minute": {"lrf_or_540": 20_000, "720": 30_000, "analysis": 12_000},
            "embed_ms_per_image": 100,
        },
    )
    slots = configured_slots(control)
    enc, cpu = min(slots["gpu_encode"], 4), min(slots["cpu"], 4)
    local, basis = _local_seconds(config, mode, footage, 200, 4)
    assert basis == "benchmark"
    assert local == (Fraction(10 * 30_000, enc) + Fraction(10 * 12_000 + 200 * 100, cpu)) / 1000
    config.set(control.local_principal, "workers.cpu", 1)
    slower, _ = _local_seconds(config, mode, footage, 200, 4)
    assert slower > local, "fewer slots, longer estimate"


def test_system_info_and_cli_report_the_machine() -> None:
    from click.testing import CliRunner
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.cli.main import cli
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    body = TestClient(app).get("/api/system/info").json()
    assert body["hardware"]["fingerprint"]
    assert body["workers"]["cpu"] >= 1
    assert body["benchmark"] is None
    assert body["rate_limits"]["anthropic"]["requests_per_minute"] == 50
    out = CliRunner().invoke(cli, ["hardware"])
    assert out.exit_code == 0, out.output
    assert "worker slots" in out.output
    assert "not measured yet" in out.output
