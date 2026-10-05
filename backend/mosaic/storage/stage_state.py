"""Which key produced an asset's current per-stage rows (``AssetStage``, ADR 0020)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from mosaic.storage.models_project import AssetStage


def mark(session: Session, asset_id: int, stage: str, key: str) -> None:
    """Record ``key`` as the producer of the rows; ``""`` while they are being rewritten."""
    row = session.get(AssetStage, (asset_id, stage))
    if row is None:
        session.add(AssetStage(asset_id=asset_id, stage=stage, key=key))
    else:
        row.key = key


def is_current(session: Session, asset_id: int, stage: str, key: str) -> bool:
    """True if the rows came from ``key``. Projects from before M1 have no record and
    were analyzed in Balanced only, so their rows match the existing artifact."""
    row = session.get(AssetStage, (asset_id, stage))
    return row is None or row.key == key
