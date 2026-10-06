"""registry hidden_at (remove from recents)

Revision ID: b3f7c2d9e415
Revises: a2d6f9b1c835
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f7c2d9e415"
down_revision: str | None = "a2d6f9b1c835"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_registry") as batch:
        batch.add_column(sa.Column("hidden_at", sa.String(40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_registry") as batch:
        batch.drop_column("hidden_at")
