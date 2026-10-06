"""Download cloud-only files (S5 "Download now"; ADR 0038).

A file that is only in iCloud (or another file provider) is a placeholder on this
computer. Reading it makes the OS download it; nothing is written to the original
(invariant 1). After reading, a scan records the files as available.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass, TaskSpec
from mosaic.jobs.registry import task
from mosaic.storage.models_project import MediaFile

CHUNK = 4 * 1024 * 1024


@task("media.cloud_download")
def cloud_download_task(ctx: TaskContext) -> dict[str, Any]:
    with ctx.project.db.session() as s:
        rels = list(s.scalars(select(MediaFile.rel_path).where(MediaFile.status == "offline")))
    done = failed = 0
    for rel in rels:
        ctx.check_cancelled()
        try:
            with open(ctx.project.root / rel, "rb") as f:  # read-only
                while f.read(CHUNK):
                    ctx.check_cancelled()
            done += 1
        except OSError:
            failed += 1  # still unavailable; the scan keeps it listed as cloud-only
    ctx.spawn(
        [
            TaskSpec(
                kind="analysis.scan",
                stage="scan",
                resource_class=ResourceClass.IO,
                label="scanning folder",
            )
        ]
    )
    return {"downloaded": done, "failed": failed}
