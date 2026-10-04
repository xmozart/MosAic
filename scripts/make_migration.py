"""Autogenerate an Alembic revision.

Usage: uv run python scripts/make_migration.py control|project "message"
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from alembic import command

from mosaic.storage.db import alembic_config


def main() -> None:
    tree, message = sys.argv[1], sys.argv[2]
    if tree not in ("control", "project"):
        raise SystemExit("tree must be 'control' or 'project'")
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp) / 'gen.db'}"
        cfg = alembic_config("control" if tree == "control" else "project", url)
        command.upgrade(cfg, "head")
        command.revision(cfg, message=message, autogenerate=True)


if __name__ == "__main__":
    main()
