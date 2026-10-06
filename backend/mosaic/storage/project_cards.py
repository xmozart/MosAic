"""Home cards (S3; ADR 0038): a small summary of each project kept in the control DB.

Computed from the project DB at checkpoints (end of a scan, an analysis stage, an edit),
so ``GET /projects`` lists every project without opening any project DB. All times are
display values: dates as ISO dates, footage as whole seconds.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from mosaic.core.clock import now_iso
from mosaic.core.time import parse_rational
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import ProjectRegistry
from mosaic.storage.models_project import Asset, Disposition, Edit, SampleFrame, Segment

COVER_FRAMES = 3  # S3: one large and two small best frames


def _cover(s: Session) -> list[int]:
    """Best frames: from clips the analysis or the user marked USE, highest quality first;
    before analysis, the first kept frames."""
    # Effective USE: a user decision overrides the analysis (invariant 10).
    user = aliased(Disposition)
    overridden = exists().where(user.segment_id == Disposition.segment_id, user.source == "user")
    used = (
        select(Segment.asset_id, func.max(Segment.quality).label("q"))
        .join(Disposition, Disposition.segment_id == Segment.id)
        .where(Disposition.status == "USE", (Disposition.source == "user") | ~overridden)
        .group_by(Segment.asset_id)
        .order_by(func.max(Segment.quality).desc())
        .limit(COVER_FRAMES)
        .subquery()
    )
    ids = [
        sid
        for (sid,) in s.execute(
            select(func.min(SampleFrame.id))
            .join(used, used.c.asset_id == SampleFrame.asset_id)
            .where(SampleFrame.kept.is_(True))
            .group_by(SampleFrame.asset_id)
            .order_by(func.max(used.c.q).desc())
        )
        if sid is not None
    ]
    if len(ids) < COVER_FRAMES:
        rejected = select(Disposition.asset_id).where(
            Disposition.source == "user", Disposition.status == "REJECT"
        )
        more = s.scalars(
            select(func.min(SampleFrame.id))
            .where(SampleFrame.kept.is_(True), SampleFrame.asset_id.not_in(rejected))
            .group_by(SampleFrame.asset_id)
            .order_by(func.min(SampleFrame.id))
            .limit(COVER_FRAMES * 2)
        )
        ids += [i for i in more if i not in ids][: COVER_FRAMES - len(ids)]
    return ids


def compute(s: Session) -> dict[str, Any]:
    clips = photos = 0
    footage = 0.0
    for kind, tb, ticks in s.execute(
        select(Asset.kind, Asset.tb, Asset.duration_ticks).where(Asset.status == "ok")
    ):
        if kind == "video":
            clips += 1
            if tb and ticks:
                footage += float(ticks * parse_rational(tb))  # display only
        elif kind in ("photo", "live_photo"):
            photos += 1
    first, last = s.execute(
        select(func.min(Asset.capture_time), func.max(Asset.capture_time)).where(
            Asset.capture_time.is_not(None)
        )
    ).one()
    analyzed = bool(s.scalar(select(func.count(Disposition.id)).where(Disposition.source == "ai")))
    latest = s.scalar(select(Edit.name).order_by(Edit.created_at.desc()).limit(1))
    return {
        "clips": clips,
        "photos": photos,
        "footage_seconds": round(footage),
        "first_date": first[:10] if first else None,
        "last_date": last[:10] if last else None,
        "cover": _cover(s),
        "analyzed": analyzed,
        "latest_edit": latest,
        "updated_at": now_iso(),
    }


def store(control: ControlDB, project_id: str, card: dict[str, Any]) -> None:
    with control.db.session() as s:
        row = s.get(ProjectRegistry, project_id)
        if row is not None:
            row.card = card


def refresh(control: ControlDB, project: Any) -> None:
    """Recompute and store a project's card (best effort: never fails the caller)."""
    with project.db.session() as s:
        card = compute(s)
    store(control, project.id, card)
