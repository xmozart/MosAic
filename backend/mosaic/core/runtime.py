"""How this process runs: desktop (default) or server (``MOSAIC_MODE=server``, ADR 0034)."""

from __future__ import annotations

import os


def server_mode() -> bool:
    return os.environ.get("MOSAIC_MODE", "desktop").strip().lower() == "server"


# Environment variables that hold MosAic's secrets (ADR 0036). Child processes that never
# need them (installed AI apps, FFmpeg, probes) don't get them (invariant 11); the worker
# does. Prefixes end with "_".
SECRET_ENV = (
    "MOSAIC_MASTER_KEY",
    "MOSAIC_MASTER_KEY_FILE",
    "MOSAIC_SECRET_",
    "MOSAIC_DESKTOP_TOKEN",
)


def secret_env(name: str) -> bool:
    return any(name == e or (e.endswith("_") and name.startswith(e)) for e in SECRET_ENV)


def scrubbed_env() -> dict[str, str]:
    """This process's environment without MosAic's secrets, for child processes."""
    return {k: v for k, v in os.environ.items() if not secret_env(k)}
