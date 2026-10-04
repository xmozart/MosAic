"""Remove library rows derived from an asset's samples before they are rebuilt.

Segments reference shots and embeddings reference samples and segments, so a stage that
replaces shots or samples must clear these first (foreign keys are enforced).
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from mosaic.storage import sqlite_vec_index
from mosaic.storage.models_project import SampleFrame, Segment, SimilarityGroup


def purge_segments(session: Session, asset_id: int) -> None:
    seg_ids = list(session.scalars(select(Segment.id).where(Segment.asset_id == asset_id)))
    sqlite_vec_index.delete_embeddings(session, "segment", seg_ids)
    if seg_ids:
        session.execute(
            update(SimilarityGroup)
            .where(SimilarityGroup.best_segment_id.in_(seg_ids))
            .values(best_segment_id=None)
        )
    session.execute(delete(Segment).where(Segment.asset_id == asset_id))


def purge_sample_derived(session: Session, asset_id: int) -> None:
    """Segments and every embedding built from this asset's samples."""
    purge_segments(session, asset_id)
    sample_ids = list(
        session.scalars(select(SampleFrame.id).where(SampleFrame.asset_id == asset_id))
    )
    sqlite_vec_index.delete_embeddings(session, "sample", sample_ids)
