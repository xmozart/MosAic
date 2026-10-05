"""asset stage: the key behind an asset's current visual/audio rows

Revision ID: a7c3e2d91f04
Revises: 6d0b6d006737
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e2d91f04"
down_revision: str | None = "6d0b6d006737"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_stage",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("asset_id", "stage"),
    )


def downgrade() -> None:
    op.drop_table("asset_stage")
