"""``/api/system/info`` and the hardware benchmark (ADR 0030)."""

from __future__ import annotations

import os
import platform
from dataclasses import asdict
from functools import lru_cache
from importlib.metadata import version
from typing import Any

from fastapi import APIRouter, Depends

from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.storage.config import ConfigService

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


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


@router.get("/health")
def health(svc: Services = Svc) -> dict[str, Any]:
    """Liveness for the container healthcheck and a reverse proxy: no sign-in, so it says
    nothing but that the control DB answers (an error is a 500: unhealthy)."""
    from sqlalchemy import text

    with svc.control.db.session() as s:
        s.execute(text("SELECT 1"))
    return {"ok": True}


@router.get("/system/info")
def system_info(svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    from mosaic.ai import ratelimit
    from mosaic.jobs.worker import configured_slots
    from mosaic.media import benchmark, hardware

    encoders, ffmpeg = _media_info()
    hw = hardware.probe()
    bench = benchmark.latest(svc.control, hw)
    config = ConfigService(svc.control)
    return {
        "mode": "desktop",
        "version": version("mosaic"),
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpus": os.cpu_count(),
            **hw.as_json(),
        },
        "encoders": list(encoders),
        "ffmpeg": dict(ffmpeg),
        # ADR 0030: the worker pool, the measured speed behind estimates, AI rate limits.
        "workers": configured_slots(svc.control),
        "benchmark": bench.as_json() if bench else None,
        "rate_limits": {p: asdict(ratelimit.limit_for(config, me, p)) for p in ratelimit.DEFAULTS},
    }


@router.post("/projects/{pid}/benchmark", status_code=202)
def post_benchmark(
    pid: str, force: bool = False, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """Measure this computer (ADR 0030); the job runs in ``pid``'s queue."""
    from mosaic.app.routers.edits import _project
    from mosaic.media.pipeline import submit_benchmark

    check(me, "analysis.run", pid)
    with _project(svc, me, pid, write=True) as project:
        return {"job_id": submit_benchmark(svc.executor, me, project, force)}
