"""project registry: folder fingerprint (external placement)

Revision ID: c5e19a7b3d20
Revises: 49b6bbec3667
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e19a7b3d20"
down_revision: str | None = "49b6bbec3667"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_registry") as batch:
        batch.add_column(sa.Column("folder_fingerprint", sa.String(length=64), nullable=True))
        batch.create_index("ix_project_registry_folder_fingerprint", ["folder_fingerprint"])


def downgrade() -> None:
    with op.batch_alter_table("project_registry") as batch:
        batch.drop_index("ix_project_registry_folder_fingerprint")
        batch.drop_column("folder_fingerprint")
