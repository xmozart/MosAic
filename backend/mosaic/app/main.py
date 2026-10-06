"""FastAPI application. M0: binds 127.0.0.1 only, no auth, authz.check on every request."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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

    app = FastAPI(title="MosAic", version="0.0.1", lifespan=lifespan)
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
    return app


def serve(port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=BIND_HOST, port=port, log_level="info")
