"""Per-provider AI rate limits (M1 step 12, ADR 0030)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from mosaic.ai import ratelimit
from mosaic.ai.ratelimit import Limiter, RateLimit


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_requests_per_minute_waits_for_the_window() -> None:
    clock = Clock()
    lim = Limiter(RateLimit(requests_per_minute=2), clock)
    for _ in range(2):
        lim.acquire(10)
        lim.release()
    assert lim._wait_s(10, clock.now) == pytest.approx(60.0)
    clock.now += 30
    assert lim._wait_s(10, clock.now) == pytest.approx(30.0)
    clock.now += 30
    assert lim._wait_s(10, clock.now) == 0


def test_tokens_per_minute_and_an_oversized_call() -> None:
    clock = Clock()
    lim = Limiter(RateLimit(tokens_per_minute=1000), clock)
    lim.acquire(600)
    lim.release()
    clock.now += 10
    lim.acquire(300)
    lim.release()
    # 900 used: 200 more must wait until the first call's 600 leave the window.
    assert lim._wait_s(200, clock.now) == pytest.approx(50.0)
    assert lim._wait_s(100, clock.now) == 0
    # Larger than the whole budget: waits until the window is empty (60 s after the
    # second call, which started 10 s after the first).
    assert lim._wait_s(5000, clock.now) == pytest.approx(60.0)
    clock.now += 60
    assert lim._wait_s(5000, clock.now) == 0, "alone in an empty window"


def test_concurrency_blocks_until_release() -> None:
    lim = Limiter(RateLimit(concurrency=1))
    lim.acquire(1)
    started = threading.Event()

    def second() -> None:
        lim.acquire(1)
        started.set()
        lim.release()

    t = threading.Thread(target=second)
    t.start()
    assert not started.wait(0.3)
    lim.release()
    assert started.wait(2)
    t.join()


def test_a_cancelled_wait_stops() -> None:
    lim = Limiter(RateLimit(concurrency=1))
    lim.acquire(1)

    class CancelledError(Exception):
        pass

    def check() -> None:
        raise CancelledError

    with pytest.raises(CancelledError):
        lim.acquire(1, check)
    assert lim._in_flight == 1


def test_slot_releases_on_error() -> None:
    limit = RateLimit(concurrency=1)
    with pytest.raises(RuntimeError), ratelimit.slot("test-provider", limit, 1):
        raise RuntimeError("boom")
    start = time.monotonic()
    with ratelimit.slot("test-provider", limit, 1):
        pass
    assert time.monotonic() - start < 1


def test_settings_override_the_provider_default() -> None:
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    config = ConfigService(control)
    me = control.local_principal
    assert ratelimit.limit_for(config, me, "anthropic") == RateLimit(50, 0, 4)
    config.set(me, "ai.rate.anthropic.tokens_per_minute", 40000)
    config.set(me, "ai.rate.anthropic.concurrency", 2)
    assert ratelimit.limit_for(config, me, "anthropic") == RateLimit(50, 40000, 2)
    assert ratelimit.limit_for(config, me, "claude-cli").concurrency == 2
    assert ratelimit.limit_for(config, me, "fake") == RateLimit()


def test_aiclient_waits_for_its_provider_and_refunds_a_cancelled_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.ai.client import AIClient
    from mosaic.jobs.context import TaskCancelledError
    from tests.unit.test_ai import _task_ctx

    monkeypatch.setitem(ratelimit.DEFAULTS, "fake", RateLimit(concurrency=1))
    ctx = _task_ctx(tmp_path, limit=5.0)
    busy = ratelimit.limiter("fake", RateLimit(concurrency=1))
    busy.acquire(1)  # another task's call is in flight
    ctx.cancelled.set()
    try:
        with pytest.raises(TaskCancelledError):
            AIClient(ctx).structured("vision", "healthcheck", 1, {})
    finally:
        busy.release()
    job = ctx.store.job(ctx.task.job_id)
    assert job is not None
    assert job.cost_usd == pytest.approx(0.0), "the reservation was returned"
    ctx.cancelled.clear()
    assert not AIClient(ctx).structured("vision", "healthcheck", 1, {}).cached
    ctx.project.close()
