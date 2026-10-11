"""edit draft ops (the storyboard's undoable op log; ADR 0067)

Revision ID: c4e8a1f05b37
Revises: b7c3e9d1a246
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1f05b37"
down_revision: str | None = "b7c3e9d1a246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edit_draft_op",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("edit_id", sa.Integer(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("op", sa.JSON(), nullable=False),
        sa.Column("undone", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["edit_id"], ["edit.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_edit_draft_op_edit_id", "edit_draft_op", ["edit_id"])
    op.create_index("ux_edit_draft_op", "edit_draft_op", ["edit_id", "seq"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_edit_draft_op", table_name="edit_draft_op")
    op.drop_index("ix_edit_draft_op_edit_id", table_name="edit_draft_op")
    op.drop_table("edit_draft_op")
