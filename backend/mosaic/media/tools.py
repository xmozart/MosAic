"""Process-wide FFmpeg binaries, license-checked once (ADR 0002 B)."""

from __future__ import annotations

import os
from functools import lru_cache

from mosaic.media.ffmpeg.capabilities import (
    Capabilities,
    FFmpegBinaries,
    ensure_license_allowed,
    locate,
    probe_capabilities,
)

ENV_ALLOW_GPL = "MOSAIC_ALLOW_GPL_FFMPEG"


@lru_cache(maxsize=1)
def media_tools() -> tuple[FFmpegBinaries, Capabilities]:
    """Locate FFmpeg and refuse GPL builds unless the dev-only override is set."""
    binaries = locate()
    caps = probe_capabilities(binaries.ffmpeg)
    allow = os.environ.get(ENV_ALLOW_GPL, "").lower() in ("1", "true", "yes")
    ensure_license_allowed(caps, allow_gpl_ffmpeg=allow)
    return binaries, caps
