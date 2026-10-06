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


PRIORITY = {"USE": 1, "MAYBE": 2, "REJECT": 3}
STATUS_OF = {v: k for k, v in PRIORITY.items()}


@dataclass(frozen=True)
class Filters:
    """S10 toolbar filters (ADR 0042). ``status`` filters by the clip's status as the tile
    shows it; rejected clips are hidden unless asked for."""

    status: str | None = None  # USE | MAYBE | REJECT | none (not analyzed)
    min_stars: int | None = None
    camera: int | None = None  # device id (0: no device)
    day: str | None = None  # YYYY-MM-DD, or "unknown"
    tag: str | None = None
    include: str | None = None  # always | never
    kind: str | None = None  # video | photo
    show_rejected: bool = False


def _prio(expr: Any) -> Any:
    from sqlalchemy import case

    return case(*((expr == k, v) for k, v in PRIORITY.items()), else_=None)


def status_table() -> Any:
    """Per asset, the tile's status and who set it, as one code: ``priority × 2``, plus 1
    when the analysis set it (priority 1 USE, 2 MAYBE, 3 REJECT; NULL: nothing decided or
    analysed). The minimum over the clip's segments is the best status, the owner's when
    tied. Each segment takes the first of: the clip's never (REJECT), its own user
    decision, the clip's always or disposition, the analysis (ADR 0042;
    ``decisions.for_segments`` is the same rule)."""
    from sqlalchemy import case

    from mosaic.storage.models_project import ClipDecision

    rule = case(
        (ClipDecision.include == "always", 1),
        else_=_prio(ClipDecision.disposition),
    )
    never = case((ClipDecision.include == "never", 3))
    seg = (
        select(
            Disposition.asset_id.label("asset_id"),
            Disposition.segment_id.label("segment_id"),
            func.max(case((Disposition.source == "user", _prio(Disposition.status)))).label("u"),
            func.max(case((Disposition.source == "ai", _prio(Disposition.status)))).label("a"),
        )
        .where(Disposition.segment_id.is_not(None))
        .group_by(Disposition.segment_id, Disposition.asset_id)
        .subquery()
    )
    clip = select(ClipDecision.asset_id, rule.label("r"), never.label("n")).subquery()
    code = func.coalesce(clip.c.n * 2, seg.c.u * 2, clip.c.r * 2, seg.c.a * 2 + 1)
    per_seg = (
        select(seg.c.asset_id, func.min(code).label("c"))
        .select_from(seg)
        .outerjoin(clip, clip.c.asset_id == seg.c.asset_id)
        .group_by(seg.c.asset_id)
        .subquery()
    )
    # A clip without analysed segments shows its own decision.
    c = func.coalesce(per_seg.c.c, func.coalesce(clip.c.n, clip.c.r) * 2)
    return (
        select(Asset.id.label("asset_id"), (c // 2).label("p"), (c % 2).label("ai"))
        .select_from(Asset)
        .outerjoin(per_seg, per_seg.c.asset_id == Asset.id)
        .outerjoin(clip, clip.c.asset_id == Asset.id)
        .subquery()
    )


def filtered(q: Any, f: Filters, st: Any) -> Any:
    from mosaic.storage.models_project import ClipDecision, ClipTag

    q = q.where(_shown()).join(st, st.c.asset_id == Asset.id)
    if f.status == "none":
        q = q.where(st.c.p.is_(None))
    elif f.status is not None:
        q = q.where(st.c.p == PRIORITY[f.status])
    elif not f.show_rejected:
        q = q.where((st.c.p.is_(None)) | (st.c.p != PRIORITY["REJECT"]))
    if f.min_stars is not None or f.include is not None:
        q = q.join(ClipDecision, ClipDecision.asset_id == Asset.id)
        if f.min_stars is not None:
            q = q.where(ClipDecision.stars >= f.min_stars)
        if f.include is not None:
            q = q.where(ClipDecision.include == f.include)
    if f.camera is not None:
        q = q.where(_device() == f.camera)
    if f.day is not None:
        q = q.where(_day() == (UNKNOWN_TIME if f.day == "unknown" else f.day))
    if f.tag is not None:
        q = q.where(Asset.id.in_(select(ClipTag.asset_id).where(ClipTag.tag == f.tag)))
    if f.kind == "video":
        q = q.where(Asset.kind == "video")
    elif f.kind == "photo":
        q = q.where(Asset.kind.in_(("photo", "live_photo")))
    return q


def rejected_hidden(session: Session, f: Filters) -> int:
    """Clips the default view hides as rejected ("Show rejected (n)")."""
    if f.show_rejected or f.status is not None:
        return 0
    st = status_table()
    q = filtered(
        select(func.count(Asset.id)).select_from(Asset),
        Filters(**{**f.__dict__, "status": "REJECT"}),
        st,
    )
    return session.scalar(q) or 0


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


def day_numbers(session: Session) -> dict[str, int]:
    """Trip day numbers as the library labels its day groups: every day with shown clips,
    so a filter never renumbers the trip (S10, S11)."""
    return {
        day: i + 1
        for i, day in enumerate(
            session.scalars(select(_day()).where(_shown()).group_by(_day()).order_by(_day()))
        )
        if day != UNKNOWN_TIME
    }


def shown(asset: Asset) -> bool:
    return asset.kind in SHOWN_KINDS and asset.status != "unsupported"


def groups(session: Session, group: str, f: Filters | None = None) -> list[dict[str, Any]]:
    f = f or Filters()
    st = status_table()
    if group == "camera":
        rows = session.execute(
            filtered(
                select(_device(), func.count(Asset.id), Device.label)
                .select_from(Asset)
                .outerjoin(Device, Device.id == Asset.device_id),
                f,
                st,
            )
            .group_by(_device())
            .order_by(_device())
        )
        return [
            {"key": str(dev), "label": label or "Unknown camera", "count": n}
            for dev, n, label in rows
        ]
    out = []
    numbers = day_numbers(session)
    for day, n in session.execute(
        filtered(select(_day(), func.count(Asset.id)).select_from(Asset), f, st)
        .group_by(_day())
        .order_by(_day())
    ):
        known = day != UNKNOWN_TIME
        out.append(
            {
                "key": day if known else "unknown",
                "label": f"Day {numbers[day]} · {day}" if known else "No date",
                "count": n,
            }
        )
    return out


def _day_key(time: str | None) -> str:
    return time[:10] if time else "unknown"


def page(
    session: Session, group: str, cursor: str | None, limit: int, f: Filters | None = None
) -> Page:
    from mosaic.library import decisions

    if group not in GROUPS:
        raise BadCursorError(f"group must be one of {', '.join(GROUPS)}")
    f = f or Filters()
    keys = _keys(group)
    st = status_table()
    q = filtered(select(Asset, *keys, st.c.p, st.c.ai).select_from(Asset), f, st)
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
    decided = decisions.decisions(session, ids)
    clip_tags = decisions.tags(session, ids)
    items = []
    for row in rows:
        a = row[0]
        time = a.capture_time
        prio, by_ai = row[-2], row[-1]
        dec = decided.get(a.id)
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
                # The tile's chip: the status shown and whether the owner set it.
                "status_shown": STATUS_OF.get(prio) if prio else None,
                "decided_by": ("ai" if by_ai else "user") if prio else None,
                "decision": decisions.clip_json(dec, clip_tags.get(a.id, [])),
                "sample_id": tiles.get(a.id),
            }
        )
    nk = len(keys)
    next_cursor = encode_cursor([*rows[-1][1 : 1 + nk], assets[-1].id]) if more and rows else None
    return Page(items, next_cursor, groups(session, group, f) if cursor is None else None)
