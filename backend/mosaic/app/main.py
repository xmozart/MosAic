"""FastAPI application. Desktop: binds 127.0.0.1, no sign-in. Server (``MOSAIC_MODE=server``):
single-admin sign-in, CSRF and a configurable bind (ADR 0034). authz.check on every request."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from mosaic.app.routers import (
    analysis,
    config,
    context,
    devices,
    edits,
    jobs,
    library,
    projects,
    search,
    system,
)
from mosaic.app.routers import auth as auth_router
from mosaic.app.services import Services
from mosaic.storage.lease import LeaseHeldError
from mosaic.storage.projects import (
    ProjectBusyError,
    ReadOnlyProjectError,
    SnapshotConflictError,
)

BIND_HOST = "127.0.0.1"


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.services.leases.shutdown()  # release held project leases (ADR 0023)

    from mosaic.app.auth import server_mode

    # Server mode: no public API explorer (it would also need a CDN script the CSP blocks).
    server = server_mode()
    app = FastAPI(
        title="MosAic",
        version="0.0.1",
        lifespan=lifespan,
        docs_url=None if server else "/docs",
        redoc_url=None if server else "/redoc",
    )
    app.state.services = services or Services.create()

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo request input: a malformed secrets request would return the key.
        errors = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(ProjectBusyError)
    @app.exception_handler(SnapshotConflictError)
    @app.exception_handler(ReadOnlyProjectError)
    async def _conflict(_request: Request, exc: Exception) -> JSONResponse:
        # Being moved; changed here and on another computer (ADR 0022); open read-only.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LeaseHeldError)
    async def _held(_request: Request, exc: LeaseHeldError) -> JSONResponse:
        # Open for editing on another computer (ADR 0023): holder info for the S0 dialog.
        h = exc.lease
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "holder": {"host": h.host, "since": h.acquired_at, "until": h.expires_at},
            },
        )

    install_security_headers(app)
    app.include_router(auth_router.router)
    app.include_router(system.router)
    app.include_router(jobs.router)
    app.include_router(config.router)
    app.include_router(edits.router)
    app.include_router(context.router)
    app.include_router(analysis.router)
    app.include_router(projects.router)
    app.include_router(devices.router)
    app.include_router(search.router)
    app.include_router(library.router)
    mount_ui(app)
    return app


def inline_script_hashes(index: Path | None) -> list[str]:
    """CSP hashes of the UI's inline scripts (the pre-paint theme script in index.html)."""
    if index is None or not index.is_file():
        return []
    html = index.read_text(encoding="utf-8")
    out = []
    for body in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S):
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        out.append(f"'sha256-{digest}'")
    return out


def install_security_headers(app: FastAPI) -> None:
    """Headers on every response (ARCHITECTURE.md §14). The CSP allows only this origin's
    scripts plus the hashed inline theme script; styles allow inline (React style props);
    frames, objects and other origins are refused."""
    root = ui_dir()
    scripts = " ".join(["'self'", *inline_script_hashes(root / "index.html" if root else None)])
    csp = (
        f"default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    )
    headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "X-Frame-Options": "DENY",
        "Cross-Origin-Opener-Policy": "same-origin",
    }

    @app.middleware("http")
    async def _headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        for k, v in headers.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


def ui_dir() -> Path | None:
    """The built web UI: ``$MOSAIC_UI_DIR``, else the repo's ``frontend/dist``."""
    env = os.environ.get("MOSAIC_UI_DIR")
    path = Path(env) if env else Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return path if (path / "index.html").is_file() else None


def mount_ui(app: FastAPI) -> None:
    """Serve the single-page app: built assets as files, every other non-API path as
    ``index.html`` (client-side routes). API paths never fall through to the UI."""
    root = ui_dir()
    if root is None:
        return
    index = root / "index.html"
    app.mount("/assets", StaticFiles(directory=root / "assets", check_dir=False), name="ui-assets")

    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def _spa(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if request.method not in ("GET", "HEAD"):
            return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root.resolve()):
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def bind_host() -> str:
    """Desktop: loopback only. Server: ``MOSAIC_BIND`` (default all interfaces, for a
    container behind a reverse proxy)."""
    from mosaic.app.auth import server_mode

    if server_mode():
        return os.environ.get("MOSAIC_BIND", "0.0.0.0")
    return BIND_HOST


def serve(port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=bind_host(), port=port, log_level="info", proxy_headers=True)
