"""project card summary

Revision ID: a2d6f9b1c835
Revises: f1c5a8e3b724
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2d6f9b1c835"
down_revision: str | None = "f1c5a8e3b724"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_registry") as batch:
        batch.add_column(sa.Column("card", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_registry") as batch:
        batch.drop_column("card")
