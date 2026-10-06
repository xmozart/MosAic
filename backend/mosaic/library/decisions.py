"""The owner's library decisions on clips (S10, S11; ADR 0042).

A clip decision (``clip_decision``, ``clip_tag``) applies to the whole clip; a decision on
one segment (a ``Disposition`` row with source ``user``) is more specific and wins. Both
are hard constraints until reset (invariant 10). For each segment, the first that applies:

1. the clip's ``never`` include: REJECT, whatever else was decided (the X key's promise);
2. the segment's own user disposition;
3. the clip's ``always`` include (USE), else the clip's disposition;
4. the analysis (the AI disposition), if any.

A clip-wide USE or ``always`` keeps the clip in edits without forcing every one of its
segments in: its best segment is forced (the editor's ``user_use``), the others are USE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.library.dispositions import effective
from mosaic.storage.models_project import Asset, ClipDecision, ClipTag, Disposition, Segment

Status = Literal["USE", "MAYBE", "REJECT"]
Include = Literal["always", "never"]
FIELDS = ("disposition", "stars", "include", "note", "live_motion")
MAX_TAGS = 50


@dataclass(frozen=True)
class SegmentDecision:
    status: str | None  # None: not analyzed and not decided
    source: str | None  # user (the segment's own) | clip | ai | None
    forced: bool  # the editor keeps it (a user USE, or the best of a kept clip)
    reasons: tuple[Any, ...] = ()


def decisions(s: Session, asset_ids: list[int]) -> dict[int, ClipDecision]:
    return {
        d.asset_id: d
        for d in s.scalars(select(ClipDecision).where(ClipDecision.asset_id.in_(asset_ids)))
    }


def tags(s: Session, asset_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for aid, tag in s.execute(
        select(ClipTag.asset_id, ClipTag.tag)
        .where(ClipTag.asset_id.in_(asset_ids))
        .order_by(ClipTag.asset_id, ClipTag.tag)
    ):
        out.setdefault(aid, []).append(tag)
    return out


def clip_rule(d: ClipDecision | None) -> str | None:
    """The status a clip decision imposes on its segments (None: none)."""
    if d is None:
        return None
    if d.include == "never":
        return "REJECT"
    if d.include == "always":
        return "USE"
    return d.disposition


def clip_never(d: ClipDecision | None) -> bool:
    return d is not None and d.include == "never"


def for_segments(s: Session, asset: Asset, segments: list[Segment]) -> dict[int, SegmentDecision]:
    """The decision in force for each of one clip's segments."""
    ids = [g.id for g in segments]
    rows = effective(s, ids)
    clip = s.get(ClipDecision, asset.id)
    rule, never = clip_rule(clip), clip_never(clip)
    out: dict[int, SegmentDecision] = {}
    for g in segments:
        d = rows.get(g.id)
        if never:
            out[g.id] = SegmentDecision("REJECT", "clip", False)
        elif d is not None and d.source == "user":
            out[g.id] = SegmentDecision(d.status, "user", d.status == "USE", tuple(d.reasons))
        elif rule is not None:
            out[g.id] = SegmentDecision(rule, "clip", False)
        elif d is not None:
            out[g.id] = SegmentDecision(d.status, "ai", False, tuple(d.reasons))
        else:
            out[g.id] = SegmentDecision(None, None, False)
    if rule == "USE":
        kept = [g for g in segments if out[g.id].source == "clip"]
        if kept and not any(out[g.id].forced for g in segments):
            best = max(kept, key=lambda g: (g.group_best, g.quality or 0.0, -g.id))
            out[best.id] = SegmentDecision("USE", "clip", True)
    return out


def user_rejected(s: Session) -> set[int]:
    """Every segment the owner has rejected, by its own decision or its clip's (the edit
    critic's ``reject_used`` check; invariant 10). Streams the clip rules."""
    seg_user: dict[int, str] = {
        sid: st
        for sid, st in s.execute(
            select(Disposition.segment_id, Disposition.status).where(
                Disposition.source == "user", Disposition.segment_id.is_not(None)
            )
        )
        if sid is not None
    }
    out = {sid for sid, st in seg_user.items() if st == "REJECT"}
    never = select(ClipDecision.asset_id).where(ClipDecision.include == "never")
    out |= set(s.scalars(select(Segment.id).where(Segment.asset_id.in_(never))))
    clip_reject = select(ClipDecision.asset_id).where(
        (ClipDecision.disposition == "REJECT") & (ClipDecision.include.is_(None))
    )
    for sid in s.scalars(select(Segment.id).where(Segment.asset_id.in_(clip_reject))):
        if seg_user.get(sid, "REJECT") == "REJECT":
            out.add(sid)
    return out


class DecisionError(ValueError):
    pass


def apply(s: Session, asset_ids: list[int], change: dict[str, Any]) -> dict[int, list[str]]:
    """Applies ``change`` to each clip; returns the fields that changed per clip.

    Keys: ``disposition``, ``stars``, ``include``, ``note``, ``live_motion`` (null resets
    one), ``tags`` (replaces the clip's tags), ``add_tags`` / ``remove_tags`` (bulk)."""
    known = set(s.scalars(select(Asset.id).where(Asset.id.in_(asset_ids))))
    missing = [a for a in asset_ids if a not in known]
    if missing:
        raise LookupError(missing[0])
    existing = decisions(s, asset_ids)
    current_tags = tags(s, asset_ids)
    changed: dict[int, list[str]] = {}
    now = now_iso()
    for aid in asset_ids:
        fields: list[str] = []
        row = existing.get(aid)
        values = {f: change[f] for f in FIELDS if f in change}
        if values and (row is not None or any(v is not None for v in values.values())):
            if row is None:
                row = ClipDecision(asset_id=aid, updated_at=now)
                s.add(row)
            for f, v in values.items():
                if getattr(row, f) != v:
                    setattr(row, f, v)
                    fields.append(f)
            if fields:
                row.updated_at = now
            if all(getattr(row, f) is None for f in FIELDS):
                s.delete(row)
        have = set(current_tags.get(aid, []))
        want = set(have)
        if "tags" in change:
            want = set(change["tags"])
        want |= set(change.get("add_tags") or [])
        want -= set(change.get("remove_tags") or [])
        if len(want) > MAX_TAGS:
            raise DecisionError(f"a clip has at most {MAX_TAGS} tags")
        if want != have:
            gone = have - want
            if gone:
                s.execute(delete(ClipTag).where(ClipTag.asset_id == aid, ClipTag.tag.in_(gone)))
            for t in sorted(want - have):
                s.add(ClipTag(asset_id=aid, tag=t))
            fields.append("tags")
        if fields:
            changed[aid] = fields
    return changed


def clip_json(d: ClipDecision | None, clip_tags: list[str]) -> dict[str, Any]:
    """What the owner decided on a clip, as the library and clip detail show it."""
    return {
        "disposition": d.disposition if d else None,
        "stars": d.stars if d else None,
        "include": d.include if d else None,
        "note": d.note if d else None,
        "live_motion": d.live_motion if d else None,
        "tags": clip_tags,
    }
