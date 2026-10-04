"""OS application-data locations."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

ENV_HOME = "MOSAIC_HOME"

WORKSPACE_DIR = "MosAic"
DESCRIPTOR_NAME = ".mosaic-project.json"


def app_data_dir() -> Path:
    """MosAic's app-data directory (control DB, logs, models). ``$MOSAIC_HOME`` overrides."""
    override = os.environ.get(ENV_HOME)
    base = (
        Path(override).expanduser()
        if override
        else Path(platformdirs.user_data_dir("MosAic", appauthor=False))
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def control_db_path() -> Path:
    return app_data_dir() / "control.db"
