"""``/api/models/local``: the local models S1 and Settings download (ADR 0058)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from mosaic.ai import local_models
from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.storage.config import ConfigService

router = APIRouter(prefix="/api/models/local")
Svc = Depends(services)
Me = Depends(principal)


def _row(svc: Services, model: local_models.LocalModel, needed: bool) -> dict[str, Any]:
    installed = model.installed()
    latest = local_models.latest_download(svc.store, model.name)
    job = None
    # A running download, or the last one when it failed (S1: "paused" with Retry).
    if latest is not None and not installed and latest.status not in ("done", "cancelled"):
        prog = svc.store.progress(latest.id)
        job = {"job_id": latest.id, "state": latest.status, "pct": prog.pct if prog else 0}
    return {
        "name": model.name,
        "label": model.label,
        "capability": model.capability,
        "provider": model.provider,
        "model": model.model,
        "bytes": model.size,
        "downloaded_bytes": model.size if installed else model.downloaded_bytes(),
        "installed": installed,
        "needed": needed,  # the configured provider profile uses it
        "job": job,
    }


@router.get("")
def list_models(svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """Every model MosAic can download, with what the current settings need first."""
    check(me, "models.read", "local")
    config = ConfigService(svc.control)
    needed = {
        m.name
        for cap in ("transcriber", "embedder")
        if (c := config.provider(me, cap))
        and (m := local_models.for_choice(c.provider, c.model)) is not None
    }
    items = [_row(svc, m, m.name in needed) for m in local_models.CATALOG.values()]
    items.sort(key=lambda r: (not r["needed"], r["capability"] != "transcriber", r["bytes"]))
    return {"items": items}


@router.post("/{name}/download", status_code=202)
def download(name: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    """Starts (or returns) the model's download job; ``job_id`` null when installed."""
    check(me, "models.write", name)
    if name not in local_models.CATALOG:
        raise HTTPException(404, "unknown model")
    job_id = local_models.ensure_download(svc.store, svc.executor, me, name)
    return {"name": name, "job_id": job_id, "installed": job_id is None}
