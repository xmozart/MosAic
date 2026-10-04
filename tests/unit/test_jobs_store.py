from __future__ import annotations

import threading
import time

import pytest

from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB


@pytest.fixture
def env() -> tuple[ControlDB, JobStore]:
    control = ControlDB()
    return control, JobStore(control.db)


def _job(store: JobStore, control: ControlDB, tasks: list[TaskSpec]) -> int:
    return store.create_job(control.local_principal, JobSpec(project_id="P", kind="t", tasks=tasks))


def _statuses(store: JobStore, job: int) -> list[str]:
    return [t.status for t in store.tasks(job)]


def test_dependencies_gate_readiness(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(
        store,
        control,
        [TaskSpec("a", "s1"), TaskSpec("b", "s2", deps=[0]), TaskSpec("c", "s2", deps=[0, 1])],
    )
    assert _statuses(store, job) == ["ready", "pending", "pending"]
    t = store.lease("w", "cpu")
    assert t is not None
    assert t.kind == "a"
    assert store.lease("w", "cpu") is None
    store.complete(t.id, "w")
    assert _statuses(store, job) == ["done", "ready", "pending"]
    t2 = store.lease("w", "cpu")
    assert t2 is not None
    store.complete(t2.id, "w")
    t3 = store.lease("w", "cpu")
    assert t3 is not None
    store.complete(t3.id, "w")
    job_row = store.job(job)
    assert job_row is not None
    assert job_row.status == "done"


def test_failure_cancels_dependents_and_fails_job(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(
        store,
        control,
        [
            TaskSpec("a", "s"),
            TaskSpec("b", "s", deps=[0]),
            TaskSpec("c", "s", deps=[1]),
            TaskSpec("d", "s"),
        ],
    )
    a = store.lease("w", "cpu")
    assert a is not None
    store.fail(a.id, "w", "boom", retryable=False)
    assert _statuses(store, job)[:3] == ["failed", "cancelled", "cancelled"]
    d = store.lease("w", "cpu")
    assert d is not None
    store.complete(d.id, "w")
    job_row = store.job(job)
    assert job_row is not None
    assert job_row.status == "failed"


def test_skipped_satisfies_dependents(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s"), TaskSpec("b", "s", deps=[0])])
    a = store.lease("w", "cpu")
    assert a is not None
    store.skip(a.id, "w", "n/a")
    assert _statuses(store, job) == ["skipped", "ready"]


def test_lease_is_exclusive_under_concurrency(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    _job(store, control, [TaskSpec("a", "s") for _ in range(40)])
    got: list[int] = []
    lock = threading.Lock()

    def grab(wid: str) -> None:
        while (t := store.lease(wid, "cpu")) is not None:
            with lock:
                got.append(t.id)

    threads = [threading.Thread(target=grab, args=(f"w{i}",)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(got) == 40
    assert len(set(got)) == 40


def test_resource_classes_are_separate(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    _job(store, control, [TaskSpec("a", "s", resource_class=ResourceClass.AI_API)])
    assert store.lease("w", "cpu") is None
    assert store.lease("w", "ai_api") is not None


def test_expired_lease_requeues_and_stale_result_is_dropped(
    env: tuple[ControlDB, JobStore],
) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s")])
    t = store.lease("dead", "cpu", lease_ms=1)
    assert t is not None
    time.sleep(0.01)
    assert store.requeue_expired() == 1
    assert _statuses(store, job) == ["ready"]
    assert not store.heartbeat(t.id, "dead")
    t2 = store.lease("alive", "cpu")
    assert t2 is not None
    assert t2.attempts == 2
    assert not store.complete(t.id, "dead")  # the crashed worker's late result is ignored
    assert store.complete(t2.id, "alive")
    events = [e.event for e in store.events(job)]
    assert events == ["leased", "requeued", "leased", "done"]


def test_retryable_failure_retries_until_max(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s", max_attempts=2)])
    for _ in range(2):
        t = store.lease("w", "cpu")
        assert t is not None
        store.fail(t.id, "w", "transient", retryable=True)
    assert _statuses(store, job) == ["failed"]


def test_cancel_pause_resume_retry(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s"), TaskSpec("b", "s")])
    store.pause(job)
    assert store.lease("w", "cpu") is None
    store.resume(job)
    t = store.lease("w", "cpu")
    assert t is not None
    assert not store.heartbeat(t.id, "other")
    assert store.heartbeat(t.id, "w")
    store.cancel(job)
    assert not store.heartbeat(t.id, "w")  # running task learns it was cancelled
    assert set(_statuses(store, job)) == {"cancelled"}
    assert store.retry_failed(job) == 2
    assert _statuses(store, job) == ["ready", "ready"]


def test_progress_and_eta_only_after_ten_percent(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s", label=f"item {i}") for i in range(20)])
    p = store.progress(job)
    assert p is not None
    assert (p.done, p.total, p.eta_ms) == (0, 20, None)
    t = store.lease("w", "cpu")
    assert t is not None
    p = store.progress(job)
    assert p is not None
    assert p.current_item == "item 0"
    store.complete(t.id, "w")
    p = store.progress(job)
    assert p is not None
    assert p.eta_ms is None  # 1/20 < 10%
    t = store.lease("w", "cpu")
    assert t is not None
    store.complete(t.id, "w")
    p = store.progress(job)
    assert p is not None
    assert p.pct == 10
    assert p.eta_ms is not None


def test_add_tasks_with_dependency_on_existing(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s")])
    a = store.tasks(job)[0]
    store.add_tasks(job, [TaskSpec("b", "s", deps=[("id", a.id)])])
    assert _statuses(store, job) == ["ready", "pending"]


def test_stale_worker_cannot_disturb_reassigned_task(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s")])
    stale = store.lease("A", "cpu", lease_ms=1)
    assert stale is not None
    time.sleep(0.01)
    store.requeue_expired()
    live = store.lease("B", "cpu")
    assert live is not None
    assert not store.fail(stale.id, "A", "late failure", retryable=True)
    assert not store.complete(stale.id, "A")
    assert _statuses(store, job) == ["leased"]
    assert store.heartbeat(live.id, "B")
    assert store.complete(live.id, "B")


def test_task_cancelled_mid_run_does_not_log_done(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(store, control, [TaskSpec("a", "s")])
    t = store.lease("w", "cpu")
    assert t is not None
    store.cancel(job)
    assert not store.complete(t.id, "w")
    assert [e.event for e in store.events(job)] == ["leased"]
    j = store.job(job)
    assert j is not None
    assert j.first_done_ms is None


def test_deep_cancel_cascade_settles_job(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    chain = [TaskSpec("a", "s")] + [TaskSpec("x", "s", deps=[i]) for i in range(100)]
    job = _job(store, control, chain)
    t = store.lease("w", "cpu")
    assert t is not None
    store.fail(t.id, "w", "boom", retryable=False)
    assert _statuses(store, job).count("cancelled") == 100
    j = store.job(job)
    assert j is not None
    assert j.status == "failed"


def test_stage_counts(env: tuple[ControlDB, JobStore]) -> None:
    control, store = env
    job = _job(
        store, control, [TaskSpec("a", "probe"), TaskSpec("b", "probe"), TaskSpec("c", "proxy")]
    )
    t = store.lease("w", "cpu")
    assert t is not None
    store.complete(t.id, "w")
    assert store.stage_counts(job) == {
        "probe": {"total": 2, "done": 1, "failed": 0},
        "proxy": {"total": 1, "done": 0, "failed": 0},
    }
