"""Library browsing: clips grouped by day or camera, one page at a time (S10; ADR 0031).

Keyset pagination over ``asset``: no offset scan, so a deep page costs what the first one
does; each page sorts the shown assets once (one row per clip, not per frame or segment;
ARCHITECTURE.md §17). Per-page details (name, segment count,
disposition counts, the tile's frame) are batched by the page's asset ids. Filters and
density options of S10 are M2; the paging contract here is what they extend.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from mosaic.storage.models_project import (
    Asset,
    Device,
    Disposition,
    MediaFile,
    SampleFrame,
    Segment,
)

GROUPS = ("day", "camera")
SHOWN_KINDS = ("video", "photo", "live_photo")
UNKNOWN_TIME = "~"  # sorts after every ISO time: undated clips come last
MAX_LIMIT = 200


class BadCursorError(ValueError):
    pass


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next_cursor: str | None
    groups: list[dict[str, Any]] | None  # first page only


def _time() -> ColumnElement[str]:
    return func.coalesce(Asset.capture_time, UNKNOWN_TIME)


def _day() -> ColumnElement[str]:
    # The date as the clip's own (corrected) time records it: the trip's local day.
    return func.substr(_time(), 1, 10)


def _device() -> ColumnElement[int]:
    return func.coalesce(Asset.device_id, 0)


def _keys(group: str) -> list[ColumnElement[Any]]:
    return [_device(), _time()] if group == "camera" else [_time()]


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")


def decode_cursor(cursor: str, group: str) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(raw)
    except (binascii.Error, ValueError) as exc:
        raise BadCursorError("invalid cursor") from exc
    if not isinstance(values, list) or len(values) != len(_keys(group)) + 1:
        raise BadCursorError("cursor does not match this grouping")
    if not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in values) or (
        not isinstance(values[-1], int)
    ):
        raise BadCursorError("invalid cursor")
    if group == "camera" and not isinstance(values[0], int):
        raise BadCursorError("invalid cursor")
    return values


def _shown() -> ColumnElement[bool]:
    return and_(Asset.kind.in_(SHOWN_KINDS), Asset.status != "unsupported")


def groups(session: Session, group: str) -> list[dict[str, Any]]:
    if group == "camera":
        rows = session.execute(
            select(_device(), func.count(Asset.id), Device.label)
            .select_from(Asset)
            .outerjoin(Device, Device.id == Asset.device_id)
            .where(_shown())
            .group_by(_device())
            .order_by(_device())
        )
        return [
            {"key": str(dev), "label": label or "Unknown camera", "count": n}
            for dev, n, label in rows
        ]
    out = []
    for i, (day, n) in enumerate(
        session.execute(
            select(_day(), func.count(Asset.id)).where(_shown()).group_by(_day()).order_by(_day())
        )
    ):
        known = day != UNKNOWN_TIME
        out.append(
            {
                "key": day if known else "unknown",
                "label": f"Day {i + 1} · {day}" if known else "No date",
                "count": n,
            }
        )
    return out


def _day_key(time: str | None) -> str:
    return time[:10] if time else "unknown"


def page(session: Session, group: str, cursor: str | None, limit: int) -> Page:
    if group not in GROUPS:
        raise BadCursorError(f"group must be one of {', '.join(GROUPS)}")
    keys = _keys(group)
    q = select(Asset, *keys).where(_shown())
    if cursor:
        after = decode_cursor(cursor, group)
        q = q.where(tuple_(*keys, Asset.id) > tuple_(*after))
    rows = list(session.execute(q.order_by(*keys, Asset.id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    assets = [r[0] for r in rows]
    ids = [a.id for a in assets]
    names = dict(
        session.execute(
            select(MediaFile.asset_id, func.min(MediaFile.rel_path))
            .where(MediaFile.asset_id.in_(ids))
            .group_by(MediaFile.asset_id)
        ).all()
    )
    seg_counts = dict(
        session.execute(
            select(Segment.asset_id, func.count(Segment.id))
            .where(Segment.asset_id.in_(ids))
            .group_by(Segment.asset_id)
        ).all()
    )
    # The effective decision per segment: a user row overrides the analysis (invariant 10).
    effective: dict[int, tuple[int, str, bool]] = {}
    for gid, aid, status, source in session.execute(
        select(
            Disposition.segment_id, Disposition.asset_id, Disposition.status, Disposition.source
        ).where(Disposition.asset_id.in_(ids), Disposition.segment_id.is_not(None))
    ):
        if gid is not None and (gid not in effective or source == "user"):
            effective[gid] = (aid, status, source == "user")
    dispositions: dict[int, dict[str, int]] = {}
    for aid, status, by_user in effective.values():
        d = dispositions.setdefault(aid, {})
        d[status] = d.get(status, 0) + 1
        if by_user:
            d["user"] = d.get("user", 0) + 1
    first = (
        select(SampleFrame.asset_id, func.min(SampleFrame.ticks).label("t"))
        .where(SampleFrame.asset_id.in_(ids), SampleFrame.kept.is_(True))
        .group_by(SampleFrame.asset_id)
        .subquery()
    )
    tiles: dict[int, int] = dict(
        session.execute(
            select(first.c.asset_id, func.min(SampleFrame.id))
            .join(
                SampleFrame,
                (SampleFrame.asset_id == first.c.asset_id) & (SampleFrame.ticks == first.c.t),
            )
            .group_by(first.c.asset_id)
        ).all()
    )
    items = []
    for row in rows:
        a = row[0]
        time = a.capture_time
        items.append(
            {
                "asset_id": a.id,
                "kind": a.kind,
                "status": a.status,
                "name": names.get(a.id),
                "group": str(a.device_id or 0) if group == "camera" else _day_key(time),
                "capture_time": time,
                "device_id": a.device_id,
                "duration": (
                    {"ticks": a.duration_ticks, "tb": a.tb}
                    if a.duration_ticks is not None and a.tb
                    else None
                ),
                "segments": seg_counts.get(a.id, 0),
                "dispositions": dispositions.get(a.id, {}),
                "sample_id": tiles.get(a.id),
            }
        )
    next_cursor = encode_cursor([*rows[-1][1:], assets[-1].id]) if more and rows else None
    return Page(items, next_cursor, groups(session, group) if cursor is None else None)
