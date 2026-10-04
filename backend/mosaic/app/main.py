"""FastAPI application. M0: binds 127.0.0.1 only, no auth, authz.check on every request."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mosaic.app.routers import config, jobs, system
from mosaic.app.services import Services

BIND_HOST = "127.0.0.1"


def create_app(services: Services | None = None) -> FastAPI:
    app = FastAPI(title="MosAic", version="0.0.1")
    app.state.services = services or Services.create()

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo request input: a malformed secrets request would return the key.
        errors = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    app.include_router(system.router)
    app.include_router(jobs.router)
    app.include_router(config.router)
    return app


def serve(port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=BIND_HOST, port=port, log_level="info")
