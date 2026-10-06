"""Library browsing (docs/ui/API_MAP.md; S10; ADR 0031)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.library import browse

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


@router.get("/projects/{pid}/library")
def library(
    pid: str,
    group: str = "day",
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=browse.MAX_LIMIT),
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """One page of clips in day or camera order: ``{items, next_cursor, groups}``;
    ``groups`` (key, label, count) only on the first page."""
    check(me, "library.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        try:
            found = browse.page(s, group, cursor, limit)
        except browse.BadCursorError as exc:
            raise HTTPException(422, str(exc)) from None
    return {"items": found.items, "next_cursor": found.next_cursor, "groups": found.groups}
