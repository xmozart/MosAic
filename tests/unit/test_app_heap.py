"""``settle_heap`` leaves the server's startup objects out of the garbage collector's
scans (ADR 0065), and collects garbage from before rather than freezing it."""

from __future__ import annotations

import gc
import inspect
import weakref


class _Node:
    def __init__(self) -> None:
        self.me = self  # a cycle: only the collector frees it


def test_settle_heap_collects_then_freezes() -> None:
    from mosaic.app.main import settle_heap

    was_enabled = gc.isenabled()
    gc.disable()  # only settle_heap may collect the cycle
    try:
        garbage = _Node()
        gone = weakref.ref(garbage)
        del garbage
        assert gone() is not None
        kept = _Node()
        settle_heap()
        assert gone() is None, "garbage is collected, never frozen"
        assert gc.get_freeze_count() > 0
        assert gc.is_tracked(kept)
    finally:
        gc.unfreeze()
        if was_enabled:
            gc.enable()


def test_serve_settles_the_heap_once_the_app_is_built() -> None:
    from mosaic.app import main

    source = inspect.getsource(main.serve)
    assert source.index("create_app(") < source.index("settle_heap()") < source.index("uvicorn.")
    assert "settle_heap" not in inspect.getsource(main.create_app)
