"""Search (docs/ui/API_MAP.md; S12; ADR 0029): hybrid visual + text over the library."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mosaic.ai.registry import embedder
from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.library import search as lib
from mosaic.storage.config import ConfigService

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


@router.get("/projects/{pid}/search")
def search(
    pid: str,
    q: str = Query(..., min_length=1, max_length=500),
    mode: str = "all",
    limit: int = Query(50, ge=1, le=200),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    check(me, "library.read", pid)
    if mode not in lib.MODES:
        raise HTTPException(422, f"mode must be one of {', '.join(lib.MODES)}")
    emb = embedder(ConfigService(svc.control), me) if mode != "speech" else None
    with _project(svc, me, pid) as project, project.db.session() as s:
        found = lib.search(s, emb, q, mode, limit)
        return {
            "query": q,
            "mode": mode,
            # "unavailable": the text model is not on this computer yet (an analysis
            # fetches it); results are then text-only.
            "visual": found.visual,
            "items": lib.describe(s, found.hits),
        }


@router.get("/projects/{pid}/search/suggestions")
def suggestions(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "library.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return {"suggestions": lib.suggestions(s)}
