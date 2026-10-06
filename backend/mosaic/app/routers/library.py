"""Library browsing and the owner's decisions (docs/ui/API_MAP.md; S10, S11; ADR 0031,
0042)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.library import browse, clip_view, decisions

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
BULK_EVENTS = 200  # more changed clips than this: one "refetch" event instead


@router.get("/projects/{pid}/library")
def library(
    pid: str,
    group: str = "day",
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=browse.MAX_LIMIT),
    status: Literal["USE", "MAYBE", "REJECT", "none"] | None = None,
    min_stars: int | None = Query(None, ge=1, le=5),
    camera: int | None = Query(None, ge=0),
    day: str | None = Query(None, pattern=r"^(\d{4}-\d{2}-\d{2}|unknown)$"),
    tag: str | None = Query(None, max_length=60),
    include: Literal["always", "never"] | None = None,
    kind: Literal["video", "photo"] | None = None,
    show_rejected: bool = False,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """One page of clips in day or camera order: ``{items, next_cursor, groups,
    rejected_hidden}``; ``groups`` and ``rejected_hidden`` on the first page only. Filters
    narrow every count (ADR 0042)."""
    check(me, "library.read", pid)
    tag = tag.strip() if tag else None  # as tags are stored
    f = browse.Filters(status, min_stars, camera, day, tag, include, kind, show_rejected)
    with _project(svc, me, pid) as project, project.db.session() as s:
        try:
            found = browse.page(s, group, cursor, limit, f)
        except browse.BadCursorError as exc:
            raise HTTPException(422, str(exc)) from None
        hidden = browse.rejected_hidden(s, f) if cursor is None else None
    return {
        "items": found.items,
        "next_cursor": found.next_cursor,
        "groups": found.groups,
        "rejected_hidden": hidden,
    }


class DecisionChange(BaseModel):
    """A change to the owner's decisions on a clip. A field set to null resets it; a field
    left out is unchanged (ADR 0042)."""

    model_config = ConfigDict(extra="forbid")

    disposition: Literal["USE", "MAYBE", "REJECT"] | None = None
    stars: int | None = Field(default=None, ge=1, le=5)
    include: Literal["always", "never"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    live_motion: bool | None = None
    tags: list[Tag] | None = Field(default=None, max_length=decisions.MAX_TAGS)
    add_tags: list[Tag] | None = Field(default=None, max_length=decisions.MAX_TAGS)
    remove_tags: list[Tag] | None = Field(default=None, max_length=decisions.MAX_TAGS)

    def change(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.model_fields_set}


class BulkChange(DecisionChange):
    asset_ids: list[int] = Field(min_length=1, max_length=10_000)

    def change(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "asset_ids"}


def _apply(
    svc: Services, me: Principal, pid: str, ids: list[int], change: dict[str, Any]
) -> dict[int, list[str]]:
    with _project(svc, me, pid, write=True) as project:
        try:
            with project.write() as s:
                changed = decisions.apply(s, ids, change)
        except LookupError as exc:
            raise HTTPException(404, f"no clip {exc.args[0]}") from None
        except decisions.DecisionError as exc:
            raise HTTPException(422, str(exc)) from None
    if len(changed) > BULK_EVENTS:
        fields = sorted({f for fs in changed.values() for f in fs})
        svc.events.publish("clip.updated", {"project_id": pid, "asset_id": None, "fields": fields})
    else:
        for aid, fields in changed.items():
            svc.events.publish(
                "clip.updated", {"project_id": pid, "asset_id": aid, "fields": fields}
            )
    return changed


@router.patch("/projects/{pid}/clips/{aid}/decision")
def patch_decision(
    pid: str, aid: int, body: DecisionChange, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """Sets the owner's decisions on one clip; returns them with the changed fields."""
    check(me, "library.write", pid)
    changed = _apply(svc, me, pid, [aid], body.change())
    with _project(svc, me, pid) as project, project.db.session() as s:
        d = decisions.decisions(s, [aid]).get(aid)
        t = decisions.tags(s, [aid]).get(aid, [])
    return {"asset_id": aid, "changed": changed.get(aid, []), **decisions.clip_json(d, t)}


@router.post("/projects/{pid}/decisions/bulk")
def bulk_decisions(
    pid: str, body: BulkChange, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """The same change on many clips (S10 BulkBar): ``{updated}``, the clips that changed."""
    check(me, "library.write", pid)
    ids = list(dict.fromkeys(body.asset_ids))
    changed = _apply(svc, me, pid, ids, body.change())
    return {"updated": len(changed)}


@router.get("/projects/{pid}/clips/{aid}")
def get_clip(
    pid: str, aid: int, show_rejected: bool = False, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """S11: the clip, its moments, the AI's reasons, quality, decisions, the edits that use
    it, similar clips and its place in the library (``show_rejected`` as the grid has it)."""
    check(me, "library.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        try:
            return clip_view.clip_detail(s, aid, show_rejected)
        except LookupError:
            raise HTTPException(404, "no such clip") from None


@router.get("/projects/{pid}/clips/{aid}/transcript")
def get_transcript(
    pid: str, aid: int, after: int | None = None, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """The clip's transcript in sentences with timed words, paged (``after``)."""
    check(me, "library.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        try:
            return clip_view.transcript(s, aid, after)
        except LookupError:
            raise HTTPException(404, "no such clip") from None
