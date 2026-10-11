"""Timing tests measure requests as ``mosaic serve`` answers them (ADR 0065)."""

from __future__ import annotations

import gc
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def as_served() -> Iterator[None]:
    """The heap as ``serve`` leaves it once its app is built (``settle_heap``); the rest
    of the test session gets its own heap back afterwards."""
    from mosaic.app.main import settle_heap

    settle_heap()
    try:
        yield
    finally:
        gc.unfreeze()
