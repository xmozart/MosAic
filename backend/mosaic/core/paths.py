"""OS application-data locations."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

ENV_HOME = "MOSAIC_HOME"
ENV_MODELS = "MOSAIC_MODELS_DIR"

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


def models_dir() -> Path:
    """Downloaded model weights (Whisper, SigLIP). ``$MOSAIC_MODELS_DIR`` overrides, so
    tests and CI can share one cache across isolated app-data directories."""
    override = os.environ.get(ENV_MODELS)
    d = Path(override).expanduser() if override else app_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d
