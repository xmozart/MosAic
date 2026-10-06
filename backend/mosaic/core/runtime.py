"""How this process runs: desktop (default) or server (``MOSAIC_MODE=server``, ADR 0034)."""

from __future__ import annotations

import os


def server_mode() -> bool:
    return os.environ.get("MOSAIC_MODE", "desktop").strip().lower() == "server"
