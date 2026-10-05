"""summaries: shot, scene, day and trip

Revision ID: b81f0c6e2a57
Revises: a7c3e2d91f04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b81f0c6e2a57"
down_revision: str | None = "a7c3e2d91f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "summary",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("ref", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("context_digest", sa.String(length=16), nullable=False),
        sa.Column("provenance_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["provenance_id"], ["provenance.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("level", "ref"),
    )


def downgrade() -> None:
    op.drop_table("summary")
