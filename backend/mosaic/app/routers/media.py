"""Media for the browser (API_MAP "Library": ``/media/...``; ADR 0037).

- ``proxy``: the clip's preview video, with HTTP range requests (seeking, Safari).
- ``frame``: one sample frame (JPEG): tiles, hover-scrub, the filmstrip.
- ``filmstrip``: evenly spaced sample frames of a clip, as ids and exact times.
- ``waveform``: peaks made by the ``media.waveform`` analysis stage.

Read-only: nothing is computed here (invariant 8). Originals are never served — only
derived artifacts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.jobs.registry import PermanentError
from mosaic.media.proxy import load_proxy
from mosaic.media.waveform import waveform_key
from mosaic.storage.artifacts import ArtifactMissingError
from mosaic.storage.models_project import Asset, SampleFrame

router = APIRouter(prefix="/api/media")
Svc = Depends(services)
Me = Depends(principal)
# An asset without a finished proxy (or no such asset): "not yet", never a 500.
_MISSING = (ArtifactMissingError, PermanentError, FileNotFoundError)
# Derived and keyed by content: safe to cache in this browser for a while.
CACHE = {"Cache-Control": "private, max-age=3600"}


@router.get("/{pid}/proxy/{aid}", response_class=Response)
def proxy(pid: str, aid: int, svc: Services = Svc, me: Principal = Me) -> Response:
    check(me, "media.read", pid)
    with _project(svc, me, pid) as project:
        try:
            px = load_proxy(project, aid)
        except _MISSING:
            raise HTTPException(404, "No preview yet.") from None
        path = px.path
    if not path.is_file():
        raise HTTPException(404, "No preview yet.")
    # FileResponse answers Range requests (206, multipart ranges) itself.
    return FileResponse(path, media_type="video/mp4", headers=CACHE)


@router.get("/{pid}/frame/{sample_id}", response_class=Response)
def frame(pid: str, sample_id: int, svc: Services = Svc, me: Principal = Me) -> Response:
    check(me, "media.read", pid)
    with _project(svc, me, pid) as project:
        with project.db.session() as s:
            row = s.get(SampleFrame, sample_id)
            key = row.image_key if row else None
        if not key or not project.artifacts.exists("frame", key):
            raise HTTPException(404, "No frame.")
        path = project.artifacts.path("frame", key)
    return FileResponse(path, media_type="image/jpeg", headers=CACHE)


@router.get("/{pid}/filmstrip/{aid}")
def filmstrip(
    pid: str,
    aid: int,
    n: int = Query(8, ge=1, le=64),
    start_ticks: int | None = None,
    end_ticks: int | None = None,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """Up to ``n`` kept sample frames, evenly spread over the clip (or over
    ``[start_ticks, end_ticks)``, in the clip's time base)."""
    check(me, "media.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        asset = s.get(Asset, aid)
        if asset is None:
            raise HTTPException(404, "No such clip.")
        q = select(SampleFrame.id, SampleFrame.ticks).where(
            SampleFrame.asset_id == aid, SampleFrame.kept.is_(True)
        )
        if start_ticks is not None:
            q = q.where(SampleFrame.ticks >= start_ticks)
        if end_ticks is not None:
            q = q.where(SampleFrame.ticks < end_ticks)
        rows = list(s.execute(q.order_by(SampleFrame.ticks)))
        picked = rows if len(rows) <= n else [rows[(i * len(rows)) // n] for i in range(n)]
        return {
            "tb": asset.tb,
            "frames": [{"sample_id": sid, "ticks": t} for sid, t in picked],
        }


@router.get("/{pid}/waveform/{aid}")
def waveform(pid: str, aid: int, svc: Services = Svc, me: Principal = Me) -> Response:
    check(me, "media.read", pid)
    with _project(svc, me, pid) as project:
        with project.db.session() as s:
            asset = s.get(Asset, aid)
            silent = asset is not None and asset.audio_stream_index is None
        if asset is None:
            raise HTTPException(404, "No such clip.")
        if silent:
            return JSONResponse({"silent": True, "bucket": None, "count": 0, "peaks": ""})
        try:
            key = waveform_key(project, load_proxy(project, aid).key)
        except _MISSING:
            raise HTTPException(404, "No waveform yet.") from None
        if not project.artifacts.exists("waveform", key):
            raise HTTPException(404, "No waveform yet.")
        data = project.artifacts.get_json("waveform", key)
    return JSONResponse({"silent": False, **data}, headers=CACHE)
