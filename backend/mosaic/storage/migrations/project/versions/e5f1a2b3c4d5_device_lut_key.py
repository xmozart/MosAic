"""device LUT key (the LUT's copy in the artifact store)

Revision ID: e5f1a2b3c4d5
Revises: d4e7a90b1c62
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f1a2b3c4d5"
down_revision: str | None = "d4e7a90b1c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("device") as batch:
        batch.add_column(sa.Column("lut_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("device") as batch:
        batch.drop_column("lut_key")
