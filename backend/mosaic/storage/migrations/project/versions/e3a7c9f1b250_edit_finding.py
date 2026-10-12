"""edit findings (critic findings with a suggested fix and the owner's status; ADR 0081)

Revision ID: e3a7c9f1b250
Revises: d9f2b6c41e08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a7c9f1b250"
down_revision: str | None = "d9f2b6c41e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edit_finding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=26), nullable=False),
        sa.Column("edit_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("frame", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=16), nullable=True),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("ops", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("applied_in_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["edit_id"], ["edit.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
    )
    op.create_index("ix_edit_finding_edit_id", "edit_finding", ["edit_id"])
    op.create_index("ux_edit_finding", "edit_finding", ["edit_id", "version", "seq"], unique=True)
    _backfill()


def _backfill() -> None:
    """Rows for the findings of every version made before this table: open, from the
    deterministic critic, as the version's JSON lists them (the DB is the source of truth:
    S17 must not show "no issues" for an older version that has some)."""
    from datetime import UTC, datetime

    from mosaic.core.ids import new_ulid

    bind = op.get_bind()
    versions = sa.table(
        "edit_version",
        sa.column("edit_id", sa.Integer),
        sa.column("version", sa.Integer),
        sa.column("findings", sa.JSON),
    )
    findings = sa.table(
        "edit_finding",
        *(
            sa.column(name, kind)
            for name, kind in (
                ("uid", sa.String),
                ("edit_id", sa.Integer),
                ("version", sa.Integer),
                ("seq", sa.Integer),
                ("source", sa.String),
                ("code", sa.String),
                ("severity", sa.String),
                ("frame", sa.Integer),
                ("event_id", sa.String),
                ("text", sa.String),
                ("ops", sa.JSON),
                ("status", sa.String),
                ("applied_in_version", sa.Integer),
                ("created_at", sa.String),
            )
        ),
    )
    now = datetime.now(UTC).isoformat()
    for edit_id, version, found in bind.execute(
        sa.select(versions.c.edit_id, versions.c.version, versions.c.findings)
    ):
        rows = [
            {
                "uid": new_ulid(),
                "edit_id": edit_id,
                "version": version,
                "seq": i,
                "source": f.get("source", "critic"),
                "code": str(f.get("code", "finding"))[:40],
                "severity": str(f.get("severity", "info"))[:10],
                "frame": int(f.get("frame", 0)),
                "event_id": f.get("event_id"),
                "text": str(f.get("text", ""))[:500],
                "ops": f.get("ops") or None,
                "status": "open",
                "applied_in_version": None,
                "created_at": now,
            }
            for i, f in enumerate(found if isinstance(found, list) else [])
            if isinstance(f, dict) and isinstance(f.get("frame", 0), int)
        ]
        if rows:
            bind.execute(sa.insert(findings), rows)


def downgrade() -> None:
    op.drop_index("ux_edit_finding", table_name="edit_finding")
    op.drop_index("ix_edit_finding_edit_id", table_name="edit_finding")
    op.drop_table("edit_finding")
