"""Request dependencies: services, principal and the per-request authz check."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request

from mosaic.app import auth, desktop
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def allowed_hosts(request: Request) -> frozenset[str] | None:
    """Desktop: loopback only (DNS rebinding). Server: ``MOSAIC_ALLOWED_HOSTS`` (comma
    separated), else any host, because a reverse proxy decides the public name."""
    configured = getattr(request.app.state, "allowed_hosts", None)
    if configured is not None:
        return frozenset(configured)
    if auth.server_mode():
        env = os.environ.get("MOSAIC_ALLOWED_HOSTS", "").strip()
        return frozenset(h.strip() for h in env.split(",") if h.strip()) or None
    return ALLOWED_HOSTS


def same_origin(request: Request) -> None:
    """For the public sign-in routes, which cannot carry a CSRF token yet: the Host must
    be allowed, and a browser's Origin (sent on every cross-site POST) must be this host.
    Stops a hostile page or a DNS-rebinding attack from claiming setup or forcing a login."""
    host_header = request.headers.get("host") or ""
    host = host_header.rsplit(":", 1)[0].strip("[]")
    allowed = allowed_hosts(request)
    if allowed is not None and host not in allowed:
        raise HTTPException(status_code=421, detail="host not allowed")
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != host_header:
        raise HTTPException(status_code=403, detail="cross-site request refused")


def desktop_allows(request: Request) -> bool:
    access = getattr(request.app.state, "desktop", None)
    if access is None:
        return True
    return bool(
        access.allows(
            request.headers.get("authorization"),
            request.cookies.get(desktop.COOKIE),
            request.headers.get("sec-fetch-site"),
        )
    )


def principal(request: Request, svc: Services = Depends(services)) -> Principal:  # noqa: B008
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    allowed = allowed_hosts(request)
    if allowed is not None and host not in allowed:
        raise HTTPException(status_code=421, detail="host not allowed")
    if not auth.server_mode() and not desktop_allows(request):
        # The packaged app's per-launch token, or its session cookie (ADR 0057).
        raise HTTPException(status_code=401, detail="Not allowed.")
    if auth.server_mode():
        # Signed in, and for writes the CSRF token echoed in a header (ADR 0034).
        ok = svc.auth.check(
            request.cookies.get(auth.SESSION_COOKIE),
            request.headers.get(auth.CSRF_HEADER),
            mutating=request.method in MUTATING,
        )
        if not ok:
            raise HTTPException(status_code=401, detail="Sign in to continue.")
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
