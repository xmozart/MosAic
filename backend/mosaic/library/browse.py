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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from mosaic.storage.models_project import (
    Asset,
    Device,
    Disposition,
    MediaFile,
    SampleFrame,
    Segment,
    VisualObservation,
)

GROUPS = ("day", "camera", "similar")
KIND = {"iphone": "phone", "gopro": "actioncam", "insta360": "360", "dji": "drone"}
NO_GROUP = 2**62  # sorts clips without a similar group after every group
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
    shot_type: str | None = None  # the vision observation's shot type of any moment
    has_speech: bool | None = None


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
    if f.has_speech is not None:
        speaking = select(Segment.asset_id).where(Segment.has_speech.is_(True))
        q = q.where(Asset.id.in_(speaking) if f.has_speech else Asset.id.not_in(speaking))
    if f.shot_type is not None:
        typed = (
            select(Segment.asset_id)
            .join(VisualObservation, VisualObservation.segment_id == Segment.id)
            .where(func.json_extract(VisualObservation.data, "$.shot_type") == f.shot_type)
        )
        q = q.where(Asset.id.in_(typed))
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


def _similar() -> ColumnElement[int]:
    """The clip's first similarity group (``NO_GROUP`` when it has none)."""
    first = (
        select(func.min(Segment.similarity_group_id))
        .where(Segment.asset_id == Asset.id)
        .correlate(Asset)
        .scalar_subquery()
    )
    return func.coalesce(first, NO_GROUP)


def _group_key(group: str) -> ColumnElement[Any]:
    return {"camera": _device, "similar": _similar}.get(group, _day)()


def _keys(group: str) -> list[ColumnElement[Any]]:
    if group == "camera":
        return [_device(), _time()]
    if group == "similar":
        return [_similar(), _time()]
    return [_time()]


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
    if group in ("camera", "similar") and not isinstance(values[0], int):
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
    """The groups of the (filtered) library with their totals: clips, photos and footage
    seconds (display). Day groups carry their trip day number and the trip context's place."""
    from mosaic.core.time import parse_rational
    from mosaic.library.context import load as load_context

    f = f or Filters()
    st = status_table()
    key = _group_key(group)
    totals: dict[Any, dict[str, Any]] = {}
    for k, kind, tb, n, ticks in session.execute(
        filtered(
            select(
                key, Asset.kind, Asset.tb, func.count(Asset.id), func.sum(Asset.duration_ticks)
            ).select_from(Asset),
            f,
            st,
        ).group_by(key, Asset.kind, Asset.tb)
    ):
        t = totals.setdefault(k, {"count": 0, "clips": 0, "photos": 0, "seconds": 0.0})
        t["count"] += n
        if kind == "video":
            t["clips"] += n
            if ticks and tb:
                t["seconds"] += float(ticks * parse_rational(tb))  # display only
        else:
            t["photos"] += n

    def stats(k: Any) -> dict[str, Any]:
        t = totals[k]
        return {
            "count": t["count"],
            "clips": t["clips"],
            "photos": t["photos"],
            "footage_seconds": round(t["seconds"]),
        }

    if group == "camera":
        labels = dict(session.execute(select(Device.id, Device.label)).all())
        return [
            {"key": str(dev), "label": labels.get(dev) or "Unknown camera", **stats(dev)}
            for dev in sorted(totals)
        ]
    if group == "similar":
        out = []
        for i, k in enumerate(sorted(totals)):
            single = k == NO_GROUP
            out.append(
                {
                    "key": "none" if single else str(k),
                    "label": "No similar clips" if single else f"Similar {i + 1}",
                    **stats(k),
                }
            )
        return out
    numbers = day_numbers(session)
    places = {d.date: d.place for d in load_context(session).days if d.place}
    out = []
    for day in sorted(totals):
        known = day != UNKNOWN_TIME
        out.append(
            {
                "key": day if known else "unknown",
                "label": f"Day {numbers[day]} · {day}" if known else "No date",
                "day": numbers.get(day) if known else None,
                "date": day if known else None,
                "place": places.get(day) if known else None,
                **stats(day),
            }
        )
    return out


def camera_json(a: Asset, labels: Mapping[int, str | None]) -> dict[str, str]:
    """A tile's camera badge (S10, S12): the device's label, else the model, else the
    profile; the kind from the profile (a still from a generic camera is a photo)."""
    label = (labels.get(a.device_id) if a.device_id else None) or a.camera_model
    kind = (
        "photo" if a.kind != "video" and a.profile == "generic" else KIND.get(a.profile, "camera")
    )
    return {"label": label or a.profile.title(), "kind": kind}


def _item_group(group: str, a: Asset, first_key: Any, time: str | None) -> str:
    if group == "camera":
        return str(a.device_id or 0)
    if group == "similar":
        return "none" if first_key == NO_GROUP else str(first_key)
    return _day_key(time)


def _day_key(time: str | None) -> str:
    return time[:10] if time else "unknown"


_NO_FACTS = {
    "caption": None,
    "shot_type": None,
    "has_speech": False,
    "similar_count": 0,
    "offline": False,
}


def _tile_facts(session: Session, ids: list[int]) -> dict[int, dict[str, Any]]:
    """Per clip of a page: the caption and shot type of its best observed moment (the AI's
    words), whether anyone speaks, and how many other clips look alike."""
    out: dict[int, dict[str, Any]] = {i: dict(_NO_FACTS) for i in ids}
    best: dict[int, tuple[Any, ...]] = {}
    ai = aliased(Disposition)
    for aid, quality, best_flag, data, ai_status in session.execute(
        select(
            Segment.asset_id, Segment.quality, Segment.group_best, VisualObservation.data, ai.status
        )
        .join(VisualObservation, VisualObservation.segment_id == Segment.id)
        .outerjoin(ai, (ai.segment_id == Segment.id) & (ai.source == "ai"))
        .where(Segment.asset_id.in_(ids))
    ):
        # A moment the analysis rejected never speaks for the clip (as S11's Why).
        rank = (
            ai_status != "REJECT",
            {"high": 2, "medium": 1}.get(data.get("interest"), 0),
            quality or 0.0,
            best_flag,
        )
        if aid not in best or rank > best[aid][0]:
            best[aid] = (rank, data)
    for aid, (_, data) in best.items():
        out[aid]["caption"] = data.get("description")
        out[aid]["shot_type"] = data.get("shot_type")
    for (aid,) in session.execute(
        select(Segment.asset_id)
        .where(Segment.asset_id.in_(ids), Segment.has_speech.is_(True))
        .distinct()
    ):
        out[aid]["has_speech"] = True
    # A file only in the cloud or on an unplugged drive: the tile says so (the proxy, if
    # made, still plays).
    for (aid,) in session.execute(
        select(MediaFile.asset_id)
        .where(MediaFile.asset_id.in_(ids), MediaFile.status.in_(("offline", "missing")))
        .distinct()
    ):
        if aid is not None:
            out[aid]["offline"] = True
    other = aliased(Segment)
    for aid, n in session.execute(
        select(Segment.asset_id, func.count(func.distinct(other.asset_id)))
        .join(
            other,
            (other.similarity_group_id == Segment.similarity_group_id)
            & (other.asset_id != Segment.asset_id),
        )
        .join(Asset, Asset.id == other.asset_id)
        .where(Segment.asset_id.in_(ids), Segment.similarity_group_id.is_not(None), _shown())
        .group_by(Segment.asset_id)
    ):
        out[aid]["similar_count"] = n
    return out


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
    tile = _tile_facts(session, ids)
    device_labels = dict(
        session.execute(
            select(Device.id, Device.label).where(
                Device.id.in_({a.device_id for a in assets if a.device_id})
            )
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
                "group": _item_group(group, a, row[1], time),
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
                "camera": camera_json(a, device_labels),
                **tile.get(a.id, _NO_FACTS),
            }
        )
    nk = len(keys)
    next_cursor = encode_cursor([*rows[-1][1 : 1 + nk], assets[-1].id]) if more and rows else None
    return Page(items, next_cursor, groups(session, group, f) if cursor is None else None)
