"""hardware benchmark

Revision ID: d7a3c9e1b402
Revises: c5e19a7b3d20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3c9e1b402"
down_revision: str | None = "c5e19a7b3d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hardware_benchmark",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("hardware", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_hardware_benchmark", "hardware_benchmark", ["fingerprint", "version"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ux_hardware_benchmark", table_name="hardware_benchmark")
    op.drop_table("hardware_benchmark")
