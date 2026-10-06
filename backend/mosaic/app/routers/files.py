"""Media roots and the server folder browser (S4, S22; API_MAP "Auth & system"; ADR 0035).

Server mode only: the desktop app uses the native folder picker. Clients see paths
relative to a media root, never the server's absolute paths (ARCHITECTURE.md §14), except
the admin, who manages the roots themselves.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from mosaic.app import auth
from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.paths import DESCRIPTOR_NAME
from mosaic.core.principal import Principal, check
from mosaic.media.scan import PHOTO_EXT, VIDEO_EXT
from mosaic.storage import media_roots
from mosaic.storage.media_roots import PathOutsideRootError, PathRefusedError

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)
MAX_ENTRIES = 500  # one page of a folder listing


def _server_only() -> None:
    if not auth.server_mode():
        raise HTTPException(404, "Not Found")


def _root_json(r: media_roots.Root, *, with_path: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"id": r.id, "label": r.label, "source": r.source}
    if with_path:
        out["path"] = str(r.path)
    return out


class RootBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    label: str | None = Field(default=None, max_length=120)


@router.get("/admin/media-roots")
def list_roots(svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    _server_only()
    check(me, "admin.media_roots.read", "*")
    return {"items": [_root_json(r, with_path=True) for r in media_roots.roots(svc.control)]}


@router.post("/admin/media-roots", status_code=201)
def add_root(body: RootBody, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    _server_only()
    check(me, "admin.media_roots.write", "*")
    try:
        root = media_roots.add(svc.control, body.path, body.label)
    except PathRefusedError as exc:
        raise HTTPException(422, str(exc)) from None
    return _root_json(root, with_path=True)


@router.delete("/admin/media-roots/{root_id}", status_code=204)
def delete_root(root_id: int, svc: Services = Svc, me: Principal = Me) -> None:
    _server_only()
    check(me, "admin.media_roots.write", str(root_id))
    if not media_roots.remove(svc.control, root_id):
        raise HTTPException(404, "Unknown media root.")


def _counts(folder: Path) -> tuple[int, int]:
    videos = photos = 0
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.name.startswith(".") or not e.is_file(follow_symlinks=False):
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                if ext in VIDEO_EXT:
                    videos += 1
                elif ext in PHOTO_EXT:
                    photos += 1
    except OSError:
        pass
    return videos, photos


@router.get("/fs/browse")
def browse(
    root: int | None = None,
    path: str = Query("", max_length=4096),
    cursor: str | None = None,
    svc: Services = Svc,
    me: Principal = Me,
) -> dict[str, Any]:
    """Without ``root``: the media roots. With it: the folders in ``path`` (relative to
    the root) with their direct video/photo counts and whether each holds a project."""
    _server_only()
    check(me, "fs.browse", f"{root}:{path}")
    if root is None:
        return {"roots": [_root_json(r, with_path=False) for r in media_roots.roots(svc.control)]}
    try:
        r = media_roots.get(svc.control, root)
        folder = media_roots.within(r, path)
    except PathOutsideRootError as exc:
        raise HTTPException(403, str(exc)) from None
    except PathRefusedError as exc:
        raise HTTPException(404, str(exc)) from None
    exists = False
    try:
        exists = folder.is_dir()
        with os.scandir(folder) as it:
            names = sorted(
                (e.name for e in it if not e.name.startswith(".")),
                key=lambda n: (n.casefold(), n),
            )
    except FileNotFoundError:
        raise HTTPException(404, "That folder doesn't exist.") from None
    except NotADirectoryError:
        raise HTTPException(404, "That folder doesn't exist.") from None
    except OSError:  # unreadable, name too long, …
        raise HTTPException(403 if exists else 404, "MosAic can't read that folder.") from None
    here = media_roots.relative(r, folder)
    if cursor is not None:
        names = [n for n in names if (n.casefold(), n) > (cursor.casefold(), cursor)]
    entries: list[dict[str, Any]] = []
    for name in names:
        try:
            inside = media_roots.within(r, f"{here}/{name}" if here else name)
            if not inside.is_dir():
                continue
            videos, photos = _counts(inside)
            has_project = (inside / DESCRIPTOR_NAME).is_file()
        except (PathRefusedError, OSError, ValueError):
            continue  # escaping links, unreadable folders: not listed
        entries.append(
            {
                "name": name,
                "path": media_roots.relative(r, inside),
                "videos": videos,
                "photos": photos,
                "has_project": has_project,
            }
        )
        if len(entries) >= MAX_ENTRIES:
            break
    rel = media_roots.relative(r, folder)
    crumbs = [{"name": r.label, "path": ""}]
    acc: list[str] = []
    for part in rel.split("/") if rel else []:
        acc.append(part)
        crumbs.append({"name": part, "path": "/".join(acc)})
    videos, photos = _counts(folder)
    try:
        here_project = (folder / DESCRIPTOR_NAME).is_file()
    except OSError:
        here_project = False
    more = len(entries) >= MAX_ENTRIES and entries[-1]["name"] != names[-1]
    return {
        "root": _root_json(r, with_path=False),
        "path": rel,
        "crumbs": crumbs,
        "here": {
            "videos": videos,
            "photos": photos,
            "has_project": here_project,
        },
        "items": entries,
        "next_cursor": entries[-1]["name"] if more else None,
    }
