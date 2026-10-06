"""photo groups: bursts and photo + video moments

Revision ID: c92d4e1f7a38
Revises: b81f0c6e2a57
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c92d4e1f7a38"
down_revision: str | None = "b81f0c6e2a57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("best_segment_id", sa.Integer(), nullable=True),
        sa.Column("provenance_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["provenance_id"], ["provenance.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "photo_group_member",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["photo_group.id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["segment.id"]),
        sa.PrimaryKeyConstraint("group_id", "segment_id"),
    )
    op.create_index("ix_photo_group_member_segment_id", "photo_group_member", ["segment_id"])


def downgrade() -> None:
    op.drop_index("ix_photo_group_member_segment_id", "photo_group_member")
    op.drop_table("photo_group_member")
    op.drop_table("photo_group")
