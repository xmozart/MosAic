"""clip decisions and tags (the owner's library decisions)

Revision ID: a8d2c5e7f190
Revises: e5f1a2b3c4d5
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d2c5e7f190"
down_revision: str | None = "e5f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clip_decision",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=8), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("include", sa.String(length=8), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("live_motion", sa.Boolean(), nullable=True),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_table(
        "clip_tag",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("asset_id", "tag"),
    )
    op.create_index("ix_clip_tag_tag", "clip_tag", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_clip_tag_tag", "clip_tag")
    op.drop_table("clip_tag")
    op.drop_table("clip_decision")
