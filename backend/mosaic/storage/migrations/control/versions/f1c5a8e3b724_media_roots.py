"""media roots

Revision ID: f1c5a8e3b724
Revises: e8b4d2a6c913
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c5a8e3b724"
down_revision: str | None = "e8b4d2a6c913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_root",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )


def downgrade() -> None:
    op.drop_table("media_root")
