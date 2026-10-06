"""Task handler registry: ``kind`` → handler.

A handler's ``is_done`` makes the task idempotent: if the output already exists the
worker marks the task done without running it (ARCHITECTURE.md §7).
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mosaic.jobs.context import TaskContext

HANDLER_MODULES: tuple[str, ...] = (
    "mosaic.media.inventory",
    "mosaic.media.proxy",
    "mosaic.media.visual",
    "mosaic.audio.analysis",
    "mosaic.media.telemetry",
    "mosaic.media.photo_stage",
    "mosaic.library.embed_task",
    "mosaic.library.photo_segment",
    "mosaic.library.segments",
    "mosaic.library.mosaics",
    "mosaic.library.vision",
    "mosaic.library.similarity",
    "mosaic.library.dispositions",
    "mosaic.editing.generate",
    "mosaic.library.context_task",
    "mosaic.library.moments",
    "mosaic.library.devices",
    "mosaic.library.summaries",
    "mosaic.library.review",
    "mosaic.render.tasks",
)
"""Modules that register production handlers; extended as pipeline stages land."""

ENV_PLUGINS = "MOSAIC_TASK_PLUGINS"

Run = Callable[["TaskContext"], dict[str, Any] | None]
IsDone = Callable[["TaskContext"], bool]


class SkipTask(Exception):  # noqa: N818 - control-flow signal, not an error
    """Raised by a handler when the task does not apply (it ends ``skipped``)."""


class PermanentError(Exception):
    """A failure that retrying cannot fix (e.g. undecodable input)."""


class DeferTask(Exception):  # noqa: N818 - control-flow signal
    """The task cannot run now (its job hit the cost limit); return it to the queue."""


class UnknownTaskKindError(PermanentError):
    pass


@dataclass(frozen=True)
class Handler:
    kind: str
    run: Run
    is_done: IsDone | None = None
    # A project checkpoint follows this task: split projects snapshot their DB into the
    # folder (ARCHITECTURE.md §4, ADR 0022). Only stage-completing project tasks set it.
    checkpoint: bool = False


_HANDLERS: dict[str, Handler] = {}


def task(
    kind: str, *, is_done: IsDone | None = None, checkpoint: bool = False
) -> Callable[[Run], Run]:
    def register(fn: Run) -> Run:
        _HANDLERS[kind] = Handler(kind, fn, is_done, checkpoint)
        return fn

    return register


def load_handlers() -> None:
    mods = list(HANDLER_MODULES)
    extra = os.environ.get(ENV_PLUGINS)
    if extra:
        mods += [m.strip() for m in extra.split(",") if m.strip()]
    for mod in mods:
        importlib.import_module(mod)


def get(kind: str) -> Handler:
    try:
        return _HANDLERS[kind]
    except KeyError:
        raise UnknownTaskKindError(f"no handler registered for task kind {kind!r}") from None
