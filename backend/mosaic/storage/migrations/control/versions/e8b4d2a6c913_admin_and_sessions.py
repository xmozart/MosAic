"""admin account and auth sessions

Revision ID: e8b4d2a6c913
Revises: d7a3c9e1b402
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4d2a6c913"
down_revision: str | None = "d7a3c9e1b402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "auth_session",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_seen_ms", sa.BigInteger(), nullable=False),
        sa.Column("expires_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_session_expires_ms", "auth_session", ["expires_ms"])


def downgrade() -> None:
    op.drop_index("ix_auth_session_expires_ms", table_name="auth_session")
    op.drop_table("auth_session")
    op.drop_table("admin_account")
