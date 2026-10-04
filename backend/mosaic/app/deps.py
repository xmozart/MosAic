"""Request dependencies: services, principal and the per-request authz check."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from mosaic.app.services import Services
from mosaic.core.principal import Principal, check

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


def principal(request: Request, svc: Services = Depends(services)) -> Principal:  # noqa: B008
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    allowed = getattr(request.app.state, "allowed_hosts", ALLOWED_HOSTS)
    if host not in allowed:
        raise HTTPException(status_code=421, detail="host not allowed")
    p = svc.principal
    # Every request is authorized through the single hook (API_MAP.md); v1 always allows.
    check(
        p,
        f"{request.method} {request.scope.get('route').path_format}"  # type: ignore[union-attr]
        if request.scope.get("route")
        else request.method,
        request.url.path,
    )
    return p
