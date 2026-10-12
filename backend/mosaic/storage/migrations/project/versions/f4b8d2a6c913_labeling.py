"""labeling questions and person links ("Help me label", S24; ADR 0085)

Revision ID: f4b8d2a6c913
Revises: e3a7c9f1b250
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b8d2a6c913"
down_revision: str | None = "e3a7c9f1b250"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "labeling_question",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=26), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("day", sa.Integer(), nullable=True),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("sample_ids", sa.JSON(), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("answered_at", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
        sa.UniqueConstraint("subject"),
    )
    op.create_table(
        "person_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["labeling_question.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_person_link_asset_id", "person_link", ["asset_id"])
    op.create_index("ux_person_link", "person_link", ["label", "asset_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_person_link", table_name="person_link")
    op.drop_index("ix_person_link_asset_id", table_name="person_link")
    op.drop_table("person_link")
    op.drop_table("labeling_question")
