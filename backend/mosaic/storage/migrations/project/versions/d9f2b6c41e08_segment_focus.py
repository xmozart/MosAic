"""segment focus point (saliency, ADR 0076)

Revision ID: d9f2b6c41e08
Revises: c4e8a1f05b37
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f2b6c41e08"
down_revision: str | None = "c4e8a1f05b37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("segment") as batch:
        batch.add_column(sa.Column("focus_x", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("focus_y", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("segment") as batch:
        batch.drop_column("focus_y")
        batch.drop_column("focus_x")
