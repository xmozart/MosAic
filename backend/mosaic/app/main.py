"""FastAPI application. M0: binds 127.0.0.1 only, no auth, authz.check on every request."""

from __future__ import annotations

from fastapi import FastAPI

from mosaic.app.routers import jobs, system
from mosaic.app.services import Services

BIND_HOST = "127.0.0.1"


def create_app(services: Services | None = None) -> FastAPI:
    app = FastAPI(title="MosAic", version="0.0.1")
    app.state.services = services or Services.create()
    app.include_router(system.router)
    app.include_router(jobs.router)
    return app


def serve(port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=BIND_HOST, port=port, log_level="info")
