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

ENV_ALLOW_GPL = "MOSAIC_ALLOW_GPL_FFMPEG"  # CI/dev override of the setting below


def _allow_gpl() -> bool:
    """The dev-only ``allow_gpl_ffmpeg`` setting (never a default), or its env override."""
    if os.environ.get(ENV_ALLOW_GPL, "").lower() in ("1", "true", "yes"):
        return True
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    try:
        return bool(ConfigService(control).get(control.local_principal, "allow_gpl_ffmpeg"))
    finally:
        control.db.dispose()


@lru_cache(maxsize=1)
def media_tools() -> tuple[FFmpegBinaries, Capabilities]:
    """Locate FFmpeg and refuse GPL builds unless ``allow_gpl_ffmpeg`` is set."""
    binaries = locate()
    caps = probe_capabilities(binaries.ffmpeg)
    if caps.license.value != "lgpl":
        ensure_license_allowed(caps, allow_gpl_ffmpeg=_allow_gpl())
    return binaries, caps


@lru_cache(maxsize=1)
def working_h264_encoders() -> tuple[str, ...]:
    """H.264 encoders in preference order that actually encode on this machine (one
    trial encode each, once per process). Listed-but-unusable encoders are skipped."""
    from mosaic.media.ffmpeg.builders import encoder_trial
    from mosaic.media.ffmpeg.run import run

    binaries, caps = media_tools()
    usable = []
    for enc in caps.h264_encoders():
        result = run(binaries, encoder_trial(enc), check=False, timeout=60)
        if result.returncode == 0:
            usable.append(enc)
    return tuple(usable)
