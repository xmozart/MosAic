"""Per-provider AI rate limits (ARCHITECTURE.md §7, ADR 0030).

Every AI call holds a slot of its provider's limiter: at most ``concurrency`` calls in
flight, ``requests_per_minute`` calls and ``tokens_per_minute`` estimated tokens in any
60-second window. Limiters are per worker process, which is the one process that runs
AI tasks (ADR 0002 K). A provider's 429 still goes through the SDK's own retries.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from mosaic.core.principal import Principal
from mosaic.core.settings import default_settings
from mosaic.storage.config import ConfigService

WINDOW_S = 60.0
POLL_S = 0.25


@dataclass(frozen=True)
class RateLimit:
    requests_per_minute: int = 0  # 0 = no limit
    tokens_per_minute: int = 0
    concurrency: int = 0


DEFAULTS: dict[str, RateLimit] = {
    # Anthropic's entry tier allows 50 requests per minute; token limits depend on the
    # account's tier and model, so they are off unless the owner sets them.
    "anthropic": RateLimit(requests_per_minute=50, concurrency=4),
    # Each call starts the installed app: a few at a time keeps the computer responsive.
    "claude-cli": RateLimit(concurrency=2),
    "codex-cli": RateLimit(concurrency=2),
}
FIELDS = ("requests_per_minute", "tokens_per_minute", "concurrency")


def limit_for(config: ConfigService, principal: Principal, provider: str) -> RateLimit:
    """The provider's default, with each positive ``ai.rate.<provider>.*`` setting."""
    base = DEFAULTS.get(provider, RateLimit())
    values = {f: getattr(base, f) for f in FIELDS}
    known = default_settings()
    for f in FIELDS:
        key = f"ai.rate.{provider}.{f}"
        if key in known:  # providers without settings keep their default
            set_to = int(config.get(principal, key))
            if set_to > 0:
                values[f] = set_to
    return RateLimit(**values)


class Limiter:
    def __init__(self, limit: RateLimit, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.clock = clock
        self._cond = threading.Condition()
        self._in_flight = 0
        self._window: deque[tuple[float, int]] = deque()  # (start, tokens)

    def _trim(self, now: float) -> None:
        while self._window and now - self._window[0][0] >= WINDOW_S:
            self._window.popleft()

    def _wait_s(self, tokens: int, now: float) -> float:
        """0 when a call with ``tokens`` may start now, else how long to wait."""
        lim = self.limit
        if lim.concurrency and self._in_flight >= lim.concurrency:
            return POLL_S  # woken by a release
        self._trim(now)
        waits = [0.0]
        if lim.requests_per_minute and len(self._window) >= lim.requests_per_minute:
            waits.append(self._window[0][0] + WINDOW_S - now)
        if lim.tokens_per_minute and self._window:
            used = sum(t for _, t in self._window)
            # A call larger than the whole budget runs alone in an empty window.
            if used + tokens > lim.tokens_per_minute:
                excess = used + tokens - lim.tokens_per_minute
                freed = 0
                for start, t in self._window:
                    freed += t
                    if freed >= excess:
                        waits.append(start + WINDOW_S - now)
                        break
                else:  # larger than the whole budget: wait for an empty window
                    waits.append(self._window[-1][0] + WINDOW_S - now)
        return max(waits)

    def acquire(self, tokens: int, check: Callable[[], None] = lambda: None) -> None:
        with self._cond:
            while True:
                wait = self._wait_s(tokens, self.clock())
                if wait <= 0:
                    break
                check()  # a cancelled task stops waiting
                self._cond.wait(timeout=min(max(wait, 0.01), POLL_S))
            self._in_flight += 1
            self._window.append((self.clock(), tokens))

    def release(self) -> None:
        with self._cond:
            self._in_flight -= 1
            self._cond.notify_all()


_limiters: dict[str, Limiter] = {}
_lock = threading.Lock()


def limiter(provider: str, limit: RateLimit) -> Limiter:
    """The process-wide limiter of ``provider`` (updated when its settings change)."""
    with _lock:
        current = _limiters.get(provider)
        if current is None:
            current = _limiters[provider] = Limiter(limit)
        elif current.limit != limit:
            current.limit = limit
        return current


@contextmanager
def slot(
    provider: str, limit: RateLimit, tokens: int, check: Callable[[], None] = lambda: None
) -> Iterator[None]:
    lim = limiter(provider, limit)
    lim.acquire(tokens, check)
    try:
        yield
    finally:
        lim.release()
