"""Task handlers used only by job-system tests (loaded via MOSAIC_TASK_PLUGINS)."""

from __future__ import annotations

import time
from typing import Any

from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import TaskSpec
from mosaic.jobs.registry import PermanentError, SkipTask, task
from mosaic.storage import provenance


def _done(ctx: TaskContext) -> bool:
    key = ctx.task.output_key
    return bool(key) and ctx.project.artifacts.exists("testout", key)


@task("test.sleep", is_done=_done)
def sleep_task(ctx: TaskContext) -> dict[str, Any]:
    deadline = time.monotonic() + ctx.params.get("ms", 50) / 1000
    while time.monotonic() < deadline:
        ctx.check_cancelled()
        time.sleep(0.01)
    with ctx.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test", algorithm_version="1"))
    assert ctx.task.output_key
    ctx.project.artifacts.put_bytes("testout", ctx.task.output_key, b"ok", provenance_id=prov)
    return {"slept": True}


@task("test.fanout")
def fanout(ctx: TaskContext) -> dict[str, Any]:
    n = ctx.params["n"]
    ids = ctx.spawn(
        [
            TaskSpec(
                kind="test.sleep",
                stage="child",
                params={"ms": 20},
                output_key=f"child-{ctx.task.id}-{i}",
            )
            for i in range(n)
        ]
    )
    return {"children": ids}


@task("test.flaky")
def flaky(ctx: TaskContext) -> None:
    if ctx.task.attempts < 2:
        raise RuntimeError("transient")


@task("test.permanent")
def permanent(_ctx: TaskContext) -> None:
    raise PermanentError("cannot decode")


@task("test.skip")
def skip(_ctx: TaskContext) -> None:
    raise SkipTask("no audio stream")


@task("test.defer")
def defer(ctx: TaskContext) -> None:
    from mosaic.jobs.registry import DeferTask

    ctx.store.pause(ctx.task.job_id, cost_limit=True)
    raise DeferTask("cost limit")
