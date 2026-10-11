from __future__ import annotations

import pytest

from mosaic.jobs.client import live_worker, wait_for_job
from mosaic.jobs.model import JobSpec, TaskSpec
from mosaic.jobs.store import JobStore, now_ms
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import WorkerRecord


def test_live_worker_ignores_stale_and_dead() -> None:
    control = ControlDB()
    assert live_worker(control) is None
    with control.db.session() as s:
        s.add(
            WorkerRecord(
                worker_id="stale", pid=1, host="h", heartbeat_ms=now_ms() - 60_000, started_at="x"
            )
        )
        s.add(
            WorkerRecord(
                worker_id="dead", pid=2**22 + 12345, host="h", heartbeat_ms=now_ms(), started_at="x"
            )
        )
    assert live_worker(control) is None
    import os

    with control.db.session() as s:
        s.add(
            WorkerRecord(
                worker_id="me", pid=os.getpid(), host="h", heartbeat_ms=now_ms(), started_at="x"
            )
        )
    rec = live_worker(control)
    assert rec is not None
    assert rec.worker_id == "me"


def test_wait_for_job_returns_and_times_out() -> None:
    control = ControlDB()
    store = JobStore(control.db)
    job = store.create_job(control.local_principal, JobSpec("P", "t", tasks=[TaskSpec("a", "s")]))
    with pytest.raises(TimeoutError):
        wait_for_job(store, job, timeout_s=0.3, poll_s=0.05)
    t = store.lease("w", "cpu")
    assert t is not None
    store.complete(t.id, "w")
    seen = []
    prog = wait_for_job(store, job, seen.append, poll_s=0.05)
    assert prog.status == "done"
    assert seen


def test_worker_started_once_while_it_registers(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaic.jobs.client as client

    control = ControlDB()
    store = JobStore(control.db)
    job = store.create_job(control.local_principal, JobSpec("P", "t", tasks=[TaskSpec("a", "s")]))
    starts: list[int] = []

    class FakeProc:
        def poll(self) -> None:
            return None

    def fake_start(exit_when_idle_s: float = 20.0) -> FakeProc:
        starts.append(1)
        return FakeProc()

    monkeypatch.setattr(client, "start_worker", fake_start)
    proc = client.ensure_worker(control)
    assert proc is not None
    with pytest.raises(TimeoutError):
        client.wait_for_job(store, job, poll_s=0.05, timeout_s=1.0, control=control, worker=proc)  # type: ignore[arg-type]
    assert len(starts) == 1


def test_dead_worker_is_restarted(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaic.jobs.client as client

    control = ControlDB()
    store = JobStore(control.db)
    job = store.create_job(control.local_principal, JobSpec("P", "t", tasks=[TaskSpec("a", "s")]))

    class Dead:
        def poll(self) -> int:
            return 1

    starts: list[int] = []
    monkeypatch.setattr(client, "start_worker", lambda *_a, **_k: starts.append(1) or Dead())
    with pytest.raises(TimeoutError):
        client.wait_for_job(store, job, poll_s=0.05, timeout_s=0.3, control=control, worker=Dead())  # type: ignore[arg-type]
    assert starts
