"""``/api/system/info``."""

from __future__ import annotations

import os
import platform
from functools import lru_cache
from importlib.metadata import version
from typing import Any

from fastapi import APIRouter, Depends

from mosaic.app.deps import principal
from mosaic.core.principal import Principal

router = APIRouter(prefix="/api")


@lru_cache(maxsize=1)
def _media_info() -> tuple[tuple[str, ...], tuple[tuple[str, Any], ...]]:
    """FFmpeg capabilities, probed once per process."""
    from mosaic.media.ffmpeg.capabilities import FFmpegNotFoundError, locate, probe_capabilities

    try:
        caps = probe_capabilities(locate().ffmpeg)
    except FFmpegNotFoundError:
        return (), (("available", False),)
    info = (("available", True), ("version", caps.version), ("license", caps.license.value))
    return tuple(caps.h264_encoders()), info


@router.get("/system/info")
def system_info(_me: Principal = Depends(principal)) -> dict[str, Any]:  # noqa: B008
    encoders, ffmpeg = _media_info()
    return {
        "mode": "desktop",
        "version": version("mosaic"),
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpus": os.cpu_count(),
        },
        "encoders": list(encoders),
        "ffmpeg": dict(ffmpeg),
    }
