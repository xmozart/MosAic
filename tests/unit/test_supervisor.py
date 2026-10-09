"""The server keeps a worker running while it has work (ADR 0056)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from mosaic.jobs.model import JobSpec, TaskSpec


class FakeProc:
    def __init__(self) -> None:
        self.pid = 4242
        self.exited = False
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.exited else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[FakeProc]:
    from mosaic.jobs import supervisor

    procs: list[FakeProc] = []

    def fake_start(*_a: Any, **_k: Any) -> FakeProc:
        procs.append(FakeProc())
        return procs[-1]

    monkeypatch.setattr(supervisor, "start_worker", fake_start)
    return procs


def _job(control: Any) -> int:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore

    spec = JobSpec(project_id="p1", kind="scan", tasks=[TaskSpec(kind="noop", stage="s")])
    return LocalExecutor(JobStore(control.db)).submit(control.local_principal, spec)


def test_starts_a_worker_only_when_there_is_work(
    started: list[FakeProc], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.jobs import supervisor
    from mosaic.jobs.store import JobStore
    from mosaic.jobs.supervisor import WorkerSupervisor
    from mosaic.storage.control import ControlDB

    clock = Clock()
    monkeypatch.setattr(supervisor.time, "monotonic", clock)
    control = ControlDB()
    sup = WorkerSupervisor(control)
    assert sup.tick() is False, "an idle server holds no worker"
    assert not started
    job = _job(control)
    assert sup.tick() is True
    assert len(started) == 1
    assert sup.tick() is False, "one worker at a time while it registers"
    JobStore(control.db).pause(job)
    clock.t += 60  # the worker went idle and exited
    started[0].exited = True
    assert sup.tick() is False, "a paused job waits for the user"
    JobStore(control.db).resume(job)
    assert sup.tick() is True, "resumed work gets a worker again"
    assert len(started) == 2


def test_a_registered_live_worker_is_enough(started: list[FakeProc]) -> None:
    from mosaic.jobs.store import now_ms
    from mosaic.jobs.supervisor import WorkerSupervisor
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_control import WorkerRecord

    control = ControlDB()
    _job(control)
    with control.db.session() as s, s.begin():
        s.add(
            WorkerRecord(
                worker_id="w", pid=os.getpid(), host="h", heartbeat_ms=now_ms(), started_at="t"
            )
        )
    assert WorkerSupervisor(control).tick() is False
    assert not started


def test_only_the_real_server_supervises(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs import supervisor
    from mosaic.storage.control import ControlDB

    made: list[Any] = []

    class Spy:
        def __init__(self, control: Any) -> None:
            made.append(self)
            self.running = False

        def start(self) -> None:
            self.running = True

        def shutdown(self) -> None:
            self.running = False

    monkeypatch.setattr(supervisor, "WorkerSupervisor", Spy)
    control = ControlDB()
    with TestClient(create_app(Services.create(control))):
        assert not made
    with TestClient(create_app(Services.create(control), supervise_workers=True)):
        assert made
        assert made[0].running
    assert not made[0].running, "stops with the server"


def test_a_worker_that_dies_at_once_is_retried_with_backoff(
    started: list[FakeProc], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.jobs import supervisor
    from mosaic.storage.control import ControlDB

    clock = Clock()
    monkeypatch.setattr(supervisor.time, "monotonic", clock)
    control = ControlDB()
    _job(control)
    sup = supervisor.WorkerSupervisor(control)
    assert sup.tick() is True
    started[-1].exited = True
    clock.t += 1
    assert sup.tick() is False, "not again right away"
    clock.t += supervisor.MIN_BACKOFF_S
    assert sup.tick() is True
    started[-1].exited = True
    clock.t += 1
    assert sup.tick() is False
    clock.t += supervisor.MIN_BACKOFF_S
    assert sup.tick() is False, "the wait doubles"
    clock.t += supervisor.MIN_BACKOFF_S
    assert sup.tick() is True
    assert len(started) == 3
    # A worker that ran a while and exited (idle) is replaced at once when work comes.
    clock.t += 300
    started[-1].exited = True
    assert sup.tick() is True


def test_a_worker_that_never_registers_is_replaced(
    started: list[FakeProc], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.jobs import supervisor
    from mosaic.storage.control import ControlDB

    clock = Clock()
    monkeypatch.setattr(supervisor.time, "monotonic", clock)
    control = ControlDB()
    _job(control)
    sup = supervisor.WorkerSupervisor(control)
    assert sup.tick() is True
    clock.t += supervisor.REGISTRATION_GRACE_S + 1
    assert sup.tick() is False, "stopped; the replacement waits out the backoff"
    assert started[0].terminated
    clock.t += supervisor.MIN_BACKOFF_S
    assert sup.tick() is True
    assert len(started) == 2
