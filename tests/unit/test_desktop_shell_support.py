"""Backend support for the desktop shell (M3 step 4; ADR 0060): menu-bar pause/resume,
the battery saver, stopping workers on quit, and the stdin lifeline."""

from __future__ import annotations

import contextlib
import http.client
import subprocess
import sys
import time
from typing import Any

import pytest

from mosaic.jobs.model import JobSpec, TaskSpec


def _job(control: Any, project: str = "p1") -> int:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore

    spec = JobSpec(project_id=project, kind="scan", tasks=[TaskSpec(kind="noop", stage="s")])
    return LocalExecutor(JobStore(control.db)).submit(control.local_principal, spec)


def test_pause_all_and_resume_all(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs.store import JobStore
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    a, b, capped = _job(control), _job(control, "p2"), _job(control)
    store = JobStore(control.db)
    store.pause(capped, cost_limit=True)
    client = TestClient(create_app(Services.create(control)), base_url="http://127.0.0.1")
    r = client.post("/api/jobs/pause-all").json()
    assert sorted(r["paused"]) == sorted([a, b])
    assert {store.job(j).status for j in (a, b)} == {"paused"}  # type: ignore[union-attr]
    r = client.post("/api/jobs/resume-all").json()
    assert sorted(r["resumed"]) == sorted([a, b])
    assert store.job(capped).status == "paused_cost_limit", "waits for a higher limit"  # type: ignore[union-attr]


def test_battery_saver_halves_the_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.jobs import worker as w
    from mosaic.storage.control import ControlDB

    power = {"battery": True}
    monkeypatch.setattr(w.hardware, "on_battery", lambda: power["battery"])
    clock = {"t": 1000.0}
    monkeypatch.setattr(w.time, "monotonic", lambda: clock["t"])
    wk = w.Worker(ControlDB(), slots={"cpu": 5, "io": 1}, battery_saver=True)
    assert wk._allowed("cpu") == 3
    assert wk._allowed("io") == 1, "never below one"
    power["battery"] = False
    assert wk._allowed("cpu") == 3, "read at most every half minute"
    clock["t"] += w.POWER_CHECK_S + 1
    assert wk._allowed("cpu") == 5
    off = w.Worker(ControlDB(), slots={"cpu": 5}, battery_saver=False)
    power["battery"] = True
    assert off._allowed("cpu") == 5, "the setting is off"


def test_power_state_is_a_bool_or_none() -> None:
    from mosaic.media.hardware import on_battery

    assert on_battery() in (True, False, None)


def test_the_supervisor_stops_its_worker_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.jobs import supervisor
    from mosaic.storage.control import ControlDB

    procs: list[subprocess.Popen[bytes]] = []

    def start(*_a: Any, **_k: Any) -> subprocess.Popen[bytes]:
        # Stands in for a worker: exits on SIGTERM (the default action).
        procs.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]))
        return procs[-1]

    monkeypatch.setattr(supervisor, "start_worker", start)
    control = ControlDB()
    _job(control)
    sup = supervisor.WorkerSupervisor(control)
    assert sup.tick() is True
    t0 = time.monotonic()
    sup.shutdown(grace_s=10)
    assert procs[0].poll() is not None, "the worker was asked to stop and did"
    assert time.monotonic() - t0 < 10


def test_serve_stops_when_the_shell_closes_its_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_desktop_serve import SERVE, TOKEN, _ready

    monkeypatch.setenv("MOSAIC_MODE", "desktop")
    proc = subprocess.Popen(
        [*SERVE, "--token-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(TOKEN + "\n")
        proc.stdin.flush()
        _ready(proc)
        assert proc.poll() is None, "runs while the shell holds stdin open"
        proc.stdin.close()  # the shell is gone
        assert proc.wait(timeout=30) == 0, "stops gracefully"
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize(
    ("out", "want"),
    [
        ("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t83%; discharging", True),
        ("Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged", False),
        ("Now drawing from 'AC Power'\n", False),  # a desktop Mac
        ("", None),
    ],
)
def test_on_battery_reads_pmset(
    monkeypatch: pytest.MonkeyPatch, out: str, want: bool | None
) -> None:
    from types import SimpleNamespace

    from mosaic.media import hardware

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out))
    assert hardware.on_battery() is want


def test_a_stopping_worker_lets_a_running_task_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """SIGTERM: no new task, but the running one gets its grace period (ADR 0060)."""
    import threading

    from mosaic.jobs import worker as w
    from mosaic.storage.control import ControlDB

    wk = w.Worker(ControlDB(), slots={"cpu": 1}, stop_grace_s=5)
    finished = threading.Event()

    def slow_slot(_rc: str, _i: int = 0) -> None:
        time.sleep(1.0)  # a task in flight when the stop comes
        finished.set()

    monkeypatch.setattr(wk, "_slot_loop", slow_slot)
    monkeypatch.setattr(w.registry, "load_handlers", lambda: None)
    t = threading.Thread(target=wk.run)
    t.start()
    time.sleep(0.2)
    wk.stop.set()
    t.join(timeout=10)
    assert finished.is_set(), "the task finished before the worker exited"


def test_shutdown_is_not_held_open_by_an_event_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app window's open /api/events must not keep the backend alive on quit: the
    lifespan cleanup (workers, leases) runs within the shutdown timeout."""
    import threading
    import urllib.request

    from tests.unit.test_desktop_serve import SERVE, TOKEN, _ready

    monkeypatch.setenv("MOSAIC_MODE", "desktop")
    proc = subprocess.Popen(
        [*SERVE, "--token-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(TOKEN + "\n")
        proc.stdin.flush()
        port = _ready(proc)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/events", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        stream = urllib.request.urlopen(req, timeout=60)  # held open, as the window does

        def drain() -> None:
            with stream, contextlib.suppress(OSError, http.client.HTTPException):
                stream.read()  # cut off by the server's shutdown: expected

        threading.Thread(target=drain, daemon=True).start()
        time.sleep(0.5)
        t0 = time.monotonic()
        proc.stdin.close()  # quit
        assert proc.wait(timeout=30) == 0
        assert time.monotonic() - t0 < 15, "the stream was cut, not waited for"
        assert proc.stderr is not None
        assert "Application shutdown complete" in proc.stderr.read(), "the lifespan cleanup ran"
    finally:
        if proc.poll() is None:
            proc.kill()
