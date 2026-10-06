"""What S13's edit cards and S20's render rows show (ADR 0047). Only reads.

Edit status, first match wins: ``generating`` (an edit job is running; with its percent),
``failed`` (the newest edit job failed after the newest version), ``new`` (no version
yet), then the latest version's renders: ``final`` (a final render is done), ``preview``
(a preview is done), ``rendering``, else ``ready``. ``preliminary`` is separate: the
version was made while the library was still being analysed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaic.editing.service import edit_ref
from mosaic.jobs.store import JobStore
from mosaic.render.plan import SHORT_SIDE
from mosaic.render.service import job_status, render_state
from mosaic.storage.models_project import Edit, EditVersion, Render, SampleFrame

PAGE = 50
RESOLUTION_LABEL = {v: ("4K" if k == "4k" else k) for k, v in SHORT_SIDE.items()}


def cover(s: Session, timeline: dict[str, Any]) -> int | None:
    """A frame of the edit's first shot: the first kept sample at or after its in point."""
    events = timeline.get("tracks", [{}])[0].get("events", [])
    if not events:
        return None
    e = events[0]
    aid = int(e["asset_id"][4:])
    q = select(SampleFrame.id).where(SampleFrame.asset_id == aid, SampleFrame.kept.is_(True))
    return s.scalar(
        q.where(SampleFrame.ticks >= e["source_in"]["ticks"]).order_by(SampleFrame.ticks).limit(1)
    ) or s.scalar(q.order_by(SampleFrame.ticks.desc()).limit(1))


def edit_cards(
    s: Session, store: JobStore, project_id: str, cursor: int | None = None, limit: int = PAGE
) -> dict[str, Any]:
    q = select(Edit).order_by(Edit.id.desc())
    if cursor is not None:
        q = q.where(Edit.id < cursor)
    edits = list(s.scalars(q.limit(limit + 1)))
    more = len(edits) > limit
    edits = edits[:limit]
    ids = [e.id for e in edits]
    running = store.edit_jobs(project_id, ids, True)
    newest_job = store.edit_jobs(project_id, ids, False)
    items = []
    for e in edits:
        count = s.scalar(select(func.count()).where(EditVersion.edit_id == e.id)) or 0
        v = s.scalar(
            select(EditVersion)
            .where(EditVersion.edit_id == e.id)
            .order_by(EditVersion.version.desc())
            .limit(1)
        )
        # (kind, state) of the latest version's renders; a pending row whose job ended
        # takes the job's end, so a failed render never reads as "rendering".
        renders = (
            [
                (
                    r.profile.get("kind"),
                    render_state(
                        r.status, job_status(store, r.job_id) if r.status == "pending" else None
                    ),
                )
                for r in s.scalars(
                    select(Render).where(Render.edit_id == e.id, Render.version == v.version)
                )
            ]
            if v
            else []
        )
        job = running.get(e.id)
        last = newest_job.get(e.id)
        pct = None
        if job is not None:
            status = "generating"
            progress = store.progress(job.id)
            pct = progress.pct if progress else 0
        elif (
            last is not None
            and last.status == "failed"
            and (v is None or last.created_at > v.created_at)
        ):
            status = "failed"
        elif v is None:
            status = "new"
        elif ("final", "done") in renders:
            status = "final"
        elif any(state == "done" for _, state in renders):
            status = "preview"
        elif any(state == "pending" for _, state in renders):
            status = "rendering"
        else:
            status = "ready"
        req = e.request or {}
        items.append(
            {
                "edit_id": e.uid,
                "display_id": edit_ref(e.id),
                "name": e.name,
                "title": v.timeline.get("title") if v else None,
                "request": req,
                "aspect": req.get("aspect", "16:9"),
                "resolution": req.get("resolution", "1080p"),
                "latest_version": v.version if v else None,
                "versions": count,
                "duration": v.timeline.get("duration") if v else None,
                "cover_sample_id": cover(s, v.timeline) if v else None,
                "status": status,
                "pct": pct,
                "job_id": job.id if job else (last.id if status == "failed" and last else None),
                "error": last.error if status == "failed" and last else None,
                "preliminary": bool(v and v.metrics.get("preliminary")),
                "created_at": e.created_at,
            }
        )
    return {"items": items, "next_cursor": edits[-1].id if more and edits else None}


def render_label(profile: dict[str, Any]) -> str:
    """``Preview · 720p``, ``Web · 1080p``, ``Web · 4K · 9:16`` (S20's preset column)."""
    w, h = int(profile.get("width") or 0), int(profile.get("height") or 0)
    res = RESOLUTION_LABEL.get(min(w, h), f"{min(w, h)}p")
    head = "Preview" if profile.get("kind") == "preview" else "Web"
    if profile.get("lossless"):
        head = "Master"
    shape = "" if not w or not h or abs(w * 9 - h * 16) <= 16 else f" · {_shape(w, h)}"
    return f"{head} · {res}{shape}"


def _shape(w: int, h: int) -> str:
    from fractions import Fraction

    from mosaic.render.plan import ASPECTS

    r = Fraction(w, h)
    return min(ASPECTS, key=lambda k: abs(ASPECTS[k] - r))


def _seconds(start: str, end: str | None) -> int | None:
    if not end:
        return None
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except ValueError:
        return None


def render_rows(
    s: Session,
    store: JobStore,
    workspace: Path,
    cursor: int | None = None,
    limit: int = PAGE,
) -> dict[str, Any]:
    from mosaic.render.tasks import output_path

    q = select(Render).order_by(Render.id.desc())
    if cursor is not None:
        q = q.where(Render.id < cursor)
    rows = list(s.scalars(q.limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    edits = {e.id: e for e in s.scalars(select(Edit).where(Edit.id.in_({r.edit_id for r in rows})))}
    items = []
    for r in rows:
        e = edits.get(r.edit_id)
        job = store.job(r.job_id) if r.job_id is not None else None
        status = render_state(r.status, job.status if job else None)
        pct, error = None, job.error if job is not None and status == "failed" else None
        if status == "pending":
            if job is None or job.status == "pending":
                status = "queued"
            elif job.status.startswith("paused"):
                status = "paused"
            else:
                status = "rendering"
                progress = store.progress(job.id)
                pct = progress.pct if progress else 0
        path = output_path(workspace, r) if r.path else None
        size = path.stat().st_size if path is not None and path.is_file() else None
        if status == "done" and size is None:
            status = "missing"  # the file was removed outside MosAic
        items.append(
            {
                "render_id": r.id,
                "edit_id": e.uid if e else None,
                "edit_name": e.name if e else None,
                "version": r.version,
                "kind": r.profile.get("kind"),
                "label": render_label(r.profile),
                "width": r.profile.get("width"),
                "height": r.profile.get("height"),
                "status": status,
                "pct": pct,
                "error": error,
                "job_id": r.job_id,
                "size_bytes": size,
                "seconds": _seconds(r.created_at, r.finished_at),
                "file": path.name if size is not None and path is not None else None,
                "metrics": r.metrics,
                "created_at": r.created_at,
                "finished_at": r.finished_at,
            }
        )
    return {
        "items": items,
        "next_cursor": rows[-1].id if more and rows else None,
        "folder": str(workspace / "renders"),  # S20: where the files are saved
    }
