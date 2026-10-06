"""devices, clock offsets and suggestions; raw vs corrected capture times

Revision ID: d4e7a90b1c62
Revises: c92d4e1f7a38
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e7a90b1c62"
down_revision: str | None = "c92d4e1f7a38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("make", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("serial", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("clock_offset_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("offset_source", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("utc_offset_min", sa.Integer(), nullable=True),
        sa.Column("lut_path", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "device_suggestion",
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("reference_device_id", sa.Integer(), nullable=False),
        sa.Column("offset_ms", sa.BigInteger(), nullable=False),
        sa.Column("utc_offset_min", sa.Integer(), nullable=True),
        sa.Column("pairs", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("provenance_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["reference_device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["provenance_id"], ["provenance.id"]),
        sa.PrimaryKeyConstraint("device_id"),
    )
    with op.batch_alter_table("asset") as batch:
        batch.add_column(sa.Column("capture_time_raw", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("device_id", sa.Integer(), nullable=True))
        batch.create_index("ix_asset_device_id", ["device_id"])
        batch.create_foreign_key("fk_asset_device", "device", ["device_id"], ["id"])
    op.execute("UPDATE asset SET capture_time_raw = capture_time")


def downgrade() -> None:
    with op.batch_alter_table("asset") as batch:
        batch.drop_constraint("fk_asset_device", type_="foreignkey")
        batch.drop_index("ix_asset_device_id")
        batch.drop_column("device_id")
        batch.drop_column("capture_time_raw")
    op.drop_table("device_suggestion")
    op.drop_table("device")
