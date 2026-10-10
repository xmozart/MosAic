"""``/api/auth/*`` (S2; ADR 0034). Server mode only; in desktop mode ``status`` reports
``mode: desktop`` and the others answer 404."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mosaic.app import auth, desktop
from mosaic.app.deps import desktop_allows, principal, same_origin, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal

router = APIRouter(prefix="/api/auth")
Svc = Depends(services)
SameOrigin = Depends(same_origin)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookies(response: Response, session: auth.Session) -> None:
    secure = auth.cookie_secure()
    response.set_cookie(
        auth.SESSION_COOKIE,
        session.token,
        max_age=auth.ABSOLUTE_S,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    # Readable by the page (double-submit CSRF); useless without the HttpOnly session.
    response.set_cookie(
        auth.CSRF_COOKIE,
        session.csrf,
        max_age=auth.ABSOLUTE_S,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _server_only() -> None:
    if not auth.server_mode():
        raise HTTPException(404, "Not Found")


def _error(exc: auth.AuthError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    body: dict[str, Any] = {"detail": str(exc)}
    if exc.retry_after:
        body["retry_after"] = exc.retry_after
    return JSONResponse(status_code=exc.status, content=body, headers=headers)


@router.get("/status")
def status(request: Request, svc: Services = Svc) -> dict[str, Any]:
    """Public: what the sign-in screen should show."""
    if not auth.server_mode():
        return {"mode": "desktop", "setup_required": False, "signed_in": desktop_allows(request)}
    token = request.cookies.get(auth.SESSION_COOKIE)
    return {
        "mode": "server",
        "setup_required": not svc.auth.has_admin(),
        "signed_in": svc.auth.check(token, None, mutating=False),
    }


@router.post("/setup")
def setup(body: PasswordBody, svc: Services = Svc, _origin: None = SameOrigin) -> Response:
    _server_only()
    try:
        session = svc.auth.setup(body.password)
    except auth.AuthError as exc:
        return _error(exc)
    response = JSONResponse({"signed_in": True, "csrf": session.csrf})
    _set_cookies(response, session)
    return response


@router.post("/login")
def login(
    body: PasswordBody, request: Request, svc: Services = Svc, _origin: None = SameOrigin
) -> Response:
    _server_only()
    try:
        session = svc.auth.login(body.password, _client(request))
    except auth.AuthError as exc:
        return _error(exc)
    response = JSONResponse({"signed_in": True, "csrf": session.csrf})
    _set_cookies(response, session)
    return response


@router.post("/logout")
def logout(request: Request, svc: Services = Svc, _me: Principal = Depends(principal)) -> Response:  # noqa: B008
    _server_only()
    svc.auth.logout(request.cookies.get(auth.SESSION_COOKIE))
    response = JSONResponse({"signed_in": False})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    response.delete_cookie(auth.CSRF_COOKIE, path="/")
    return response


@router.post("/desktop-session")
def desktop_session(request: Request) -> Response:
    """Desktop: trade the shell's token (``Authorization: Bearer``) for an HttpOnly session
    cookie on this origin, so media elements and the event stream are let in (ADR 0057)."""
    access = getattr(request.app.state, "desktop", None)
    if auth.server_mode() or access is None or not access.enforced:
        raise HTTPException(404, "Not Found")
    if not access.bearer_ok(request.headers.get("authorization")):
        raise HTTPException(401, "Not allowed.")
    response = JSONResponse({"signed_in": True})
    response.set_cookie(
        desktop.COOKIE, access.new_session(), httponly=True, samesite="strict", path="/"
    )
    return response
