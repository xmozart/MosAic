"""tech_metric time index (a clip's ranges of one metric, in time order; ADR 0065); it
leads with asset_id, so the asset_id index it covers is dropped

Revision ID: b7c3e9d1a246
Revises: a8d2c5e7f190
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7c3e9d1a246"
down_revision: str | None = "a8d2c5e7f190"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_tech_metric_asset_name_start", "tech_metric", ["asset_id", "name", "start_ticks"]
    )
    op.drop_index("ix_tech_metric_asset_id", table_name="tech_metric")


def downgrade() -> None:
    op.create_index("ix_tech_metric_asset_id", "tech_metric", ["asset_id"])
    op.drop_index("ix_tech_metric_asset_name_start", table_name="tech_metric")
