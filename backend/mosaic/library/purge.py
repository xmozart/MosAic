"""Remove library rows derived from an asset's samples before they are rebuilt.

Segments reference shots and embeddings reference samples and segments, so a stage that
replaces shots or samples must clear these first (foreign keys are enforced). Mosaics,
vision observations and AI dispositions are derived from segments and go with them; user
dispositions are detached, never deleted (invariant 10, ADR 0013).
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from mosaic.storage import sqlite_vec_index
from mosaic.storage.models_project import (
    Disposition,
    Mosaic,
    MosaicTile,
    SampleFrame,
    Segment,
    SimilarityGroup,
    VisualObservation,
)


def purge_mosaics(session: Session, asset_id: int) -> None:
    """An asset's mosaics, their tiles and the observations made from them."""
    mosaic_ids = select(Mosaic.id).where(Mosaic.asset_id == asset_id)
    session.execute(delete(VisualObservation).where(VisualObservation.mosaic_id.in_(mosaic_ids)))
    session.execute(delete(MosaicTile).where(MosaicTile.mosaic_id.in_(mosaic_ids)))
    session.execute(delete(Mosaic).where(Mosaic.asset_id == asset_id))


def purge_segments(session: Session, asset_id: int) -> None:
    seg_ids = list(session.scalars(select(Segment.id).where(Segment.asset_id == asset_id)))
    purge_mosaics(session, asset_id)
    sqlite_vec_index.delete_embeddings(session, "segment", seg_ids)
    if seg_ids:
        session.execute(
            update(SimilarityGroup)
            .where(SimilarityGroup.best_segment_id.in_(seg_ids))
            .values(best_segment_id=None)
        )
        session.execute(
            delete(Disposition).where(
                Disposition.segment_id.in_(seg_ids), Disposition.source != "user"
            )
        )
        session.execute(
            update(Disposition).where(Disposition.segment_id.in_(seg_ids)).values(segment_id=None)
        )
    session.execute(delete(Segment).where(Segment.asset_id == asset_id))


def purge_sample_derived(session: Session, asset_id: int) -> None:
    """Segments and every embedding built from this asset's samples."""
    purge_segments(session, asset_id)
    sample_ids = list(
        session.scalars(select(SampleFrame.id).where(SampleFrame.asset_id == asset_id))
    )
    sqlite_vec_index.delete_embeddings(session, "sample", sample_ids)


def reattach_user_dispositions(session: Session, asset_id: int) -> int:
    """Attach detached user rows of ``asset_id`` to the segment their anchor overlaps
    most. The newest decision wins a segment; others stay detached, never deleted."""
    detached = list(
        session.scalars(
            select(Disposition)
            .where(
                Disposition.asset_id == asset_id,
                Disposition.source == "user",
                Disposition.segment_id.is_(None),
            )
            .order_by(Disposition.updated_at.desc(), Disposition.id.desc())
        )
    )
    if not detached:
        return 0
    segments = list(
        session.execute(
            select(Segment.id, Segment.start_ticks, Segment.end_ticks).where(
                Segment.asset_id == asset_id
            )
        )
    )
    taken = set(
        session.scalars(
            select(Disposition.segment_id).where(
                Disposition.asset_id == asset_id,
                Disposition.source == "user",
                Disposition.segment_id.is_not(None),
            )
        )
    )
    attached = 0
    for row in detached:
        best = max(
            (
                (min(b, row.anchor_end_ticks) - max(a, row.anchor_start_ticks), sid)
                for sid, a, b in segments
            ),
            default=(0, None),
        )
        overlap, sid = best
        if sid is None or overlap <= 0 or sid in taken:
            continue
        row.segment_id = sid
        taken.add(sid)
        attached += 1
    session.flush()
    return attached
