"""Server-mode sign-in, sessions and CSRF (M2 step 3a; S2; ADR 0034)."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"


def _client(monkeypatch: pytest.MonkeyPatch, mode: str) -> tuple[TestClient, object]:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_MODE", mode)
    control = ControlDB()
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    # Secure cookies travel only over https.
    return TestClient(app, base_url="https://testserver"), control


def test_desktop_mode_needs_no_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, "desktop")
    assert client.get("/api/auth/status").json() == {
        "mode": "desktop",
        "setup_required": False,
        "signed_in": True,
    }
    assert client.get("/api/jobs").status_code == 200
    assert client.post("/api/auth/setup", json={"password": PASSWORD}).status_code == 404


def test_first_run_setup_then_sign_in_with_strict_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, "server")
    status = client.get("/api/auth/status").json()
    assert status == {"mode": "server", "setup_required": True, "signed_in": False}
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/auth/setup", json={"password": "short"}).status_code == 422
    r = client.post("/api/auth/setup", json={"password": PASSWORD})
    assert r.status_code == 200
    csrf = r.json()["csrf"]
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("mosaic_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("mosaic_csrf="))
    for flag in ("HttpOnly", "Secure", "SameSite=strict"):
        assert flag.lower() in session.lower(), flag
    assert "httponly" not in csrf_cookie.lower(), "the page reads the CSRF cookie"
    assert "samesite=strict" in csrf_cookie.lower()
    assert client.get("/api/auth/status").json()["signed_in"] is True
    assert client.get("/api/jobs").status_code == 200
    again = client.post("/api/auth/setup", json={"password": PASSWORD})
    assert again.status_code == 409, "one admin account"
    assert csrf


def test_mutating_requests_need_the_csrf_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, "server")
    csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]
    body = {"analysis.mode": "quick"}
    assert client.patch("/api/settings", json=body).status_code == 401
    assert (
        client.patch("/api/settings", json=body, headers={"X-CSRF-Token": "x"}).status_code == 401
    )
    ok = client.patch("/api/settings", json=body, headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200, ok.text
    # Reads need no token.
    assert client.get("/api/settings").status_code == 200


def test_wrong_password_then_lockout_with_countdown(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, "server")
    client.post("/api/auth/setup", json={"password": PASSWORD})
    client.cookies.clear()
    for _ in range(4):
        r = client.post("/api/auth/login", json={"password": "wrong password!"})
        assert r.status_code == 401
        assert r.json()["detail"] == "That password didn't match. Try again."
    r = client.post("/api/auth/login", json={"password": "wrong password!"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert r.json()["retry_after"] > 0
    locked = client.post("/api/auth/login", json={"password": PASSWORD})
    assert locked.status_code == 429, "even the right password waits out the lock"


def test_only_hashes_are_stored_and_logout_ends_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, control = _client(monkeypatch, "server")
    csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]
    token = client.cookies.get("mosaic_session")
    assert token
    db_file = Path(control.db.path)  # type: ignore[attr-defined]
    raw = b"".join(p.read_bytes() for p in db_file.parent.glob(db_file.name + "*"))
    for secret in (PASSWORD, token, csrf):
        assert secret.encode() not in raw, "stored in plain text"
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    client.cookies.set("mosaic_session", token)  # replaying the old cookie
    assert client.get("/api/jobs").status_code == 401


def test_security_headers_and_csp_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = "document.documentElement.dataset.theme='dark';"
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(f"<html><script>{script}</script></html>")
    monkeypatch.setenv("MOSAIC_UI_DIR", str(tmp_path))
    client, _ = _client(monkeypatch, "desktop")
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    api = client.get("/api/auth/status")
    assert api.headers["cache-control"] == "no-store"


def test_sessions_expire_when_idle_and_absolutely(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.app import auth

    now = [1_000_000_000_000]
    monkeypatch.setattr(auth, "_now_ms", lambda: now[0])
    client, control = _client(monkeypatch, "server")
    client.post("/api/auth/setup", json={"password": PASSWORD})
    token = client.cookies.get("mosaic_session")
    now[0] += auth.IDLE_MS - 1000
    assert client.get("/api/jobs").status_code == 200, "used within the idle window"
    now[0] += auth.IDLE_MS + 1000
    assert client.get("/api/jobs").status_code == 401, "idle too long"
    from mosaic.storage.models_control import AuthSession

    with control.db.session() as s:  # type: ignore[attr-defined]
        assert s.get(AuthSession, auth._digest(token)) is None, "the row is deleted"

    client.post("/api/auth/login", json={"password": PASSWORD})
    start = now[0]
    for _ in range(40):  # active all the time, but the absolute limit still ends it
        now[0] += auth.IDLE_MS // 2
        if now[0] - start > auth.ABSOLUTE_MS:
            break
        assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/jobs").status_code == 401


def test_lockouts_double_and_reset_on_success() -> None:
    from mosaic.app.auth import FAILURES_BEFORE_LOCK, LOCK_MAX_S, LOCK_S, Throttle

    t = [0.0]
    th = Throttle(clock=lambda: t[0])

    def fail_until_locked() -> int:
        for _ in range(FAILURES_BEFORE_LOCK):
            assert th.attempt("a") == 0
        return th.attempt("a")

    assert fail_until_locked() == LOCK_S
    assert th.attempt("b") == 0, "other clients are not affected"
    t[0] += LOCK_S
    assert fail_until_locked() == LOCK_S * 2
    t[0] += LOCK_S * 2
    assert fail_until_locked() == LOCK_S * 4
    for _ in range(10):
        t[0] += LOCK_MAX_S
        wait = fail_until_locked()
    assert wait == LOCK_MAX_S, "capped"
    t[0] += LOCK_MAX_S
    assert th.attempt("a") == 0
    th.succeeded("a")
    t[0] += 1
    assert fail_until_locked() == LOCK_S, "a success resets the doubling"
    # Old failures do not add up with new ones much later.
    for _ in range(FAILURES_BEFORE_LOCK - 1):
        assert th.attempt("c") == 0
    t[0] += LOCK_MAX_S + 1
    for _ in range(FAILURES_BEFORE_LOCK - 1):  # a fresh budget, not one left
        assert th.attempt("c") == 0
        assert th.wait_s("c") == 0, "the earlier failures were forgotten"


def test_public_sign_in_refuses_other_sites_and_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, "server")
    hostile = client.post(
        "/api/auth/setup", json={"password": PASSWORD}, headers={"Origin": "https://evil.example"}
    )
    assert hostile.status_code == 403
    rebinding = client.post(
        "/api/auth/login", json={"password": PASSWORD}, headers={"Host": "evil.example"}
    )
    assert rebinding.status_code == 421
    same = client.post(
        "/api/auth/setup", json={"password": PASSWORD}, headers={"Origin": "https://testserver"}
    )
    assert same.status_code == 200


def test_allowed_hosts_setting_in_server_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_MODE", "server")
    app = create_app(Services.create(ControlDB()))  # no test override of the host list
    client = TestClient(app, base_url="https://mosaic.lan")
    assert client.get("/api/auth/status").status_code == 200
    assert client.get("/api/jobs").status_code == 401, "any host, but signed out"
    monkeypatch.setenv("MOSAIC_ALLOWED_HOSTS", "mosaic.lan, nas.local")
    assert client.get("/api/jobs").status_code == 401
    other = TestClient(app, base_url="https://evil.example")
    assert other.get("/api/jobs").status_code == 421


def test_every_route_but_sign_in_needs_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route surface guard: a router that forgets the principal dependency fails here."""
    client, _ = _client(monkeypatch, "server")
    public = {"/api/auth/status", "/api/auth/setup", "/api/auth/login"}
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    checked = 0
    for path, ops in paths.items():
        if path in public:
            continue
        url = path.replace("{ref}", "ai/anthropic")
        for part in ("{pid}", "{eid}", "{job_id}", "{version}", "{aid}", "{rid}"):
            url = url.replace(part, "1")
        for method in ops:
            r = client.request(method.upper(), url, json={})
            assert r.status_code == 401, (method, path, r.status_code)
            checked += 1
    assert checked > 20
    # Hidden routes (not in the schema) under /api must not skip the guard either. None
    # exist today, so mount one the way a careless router would and check it is caught.
    from fastapi import Depends
    from fastapi.routing import APIRoute

    from mosaic.app.deps import principal

    app = client.app  # type: ignore[attr-defined]

    def _probe(_me: object = Depends(principal)) -> dict[str, bool]:
        return {"ok": True}

    app.add_api_route("/api/_hidden_probe", _probe, methods=["GET"], include_in_schema=False)
    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the UI's catch-all

    hidden = [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and not r.include_in_schema and r.path.startswith("/api")
    ]
    assert [r.path for r in hidden] == ["/api/_hidden_probe"]
    for r in hidden:
        for method in r.methods:
            assert client.request(method, r.path).status_code == 401


def test_every_api_route_depends_on_the_session_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Static guard (stronger than calling routes): each /api route but sign-in has
    ``deps.principal`` somewhere in its dependency tree, so a forgotten ``Me`` fails here."""
    from fastapi.dependencies.models import Dependant
    from fastapi.routing import APIRoute

    from mosaic.app.deps import principal

    client, _ = _client(monkeypatch, "server")
    public = {"/api/auth/status", "/api/auth/setup", "/api/auth/login"}

    def uses_principal(d: Dependant) -> bool:
        return any(sub.call is principal or uses_principal(sub) for sub in d.dependencies)

    missing = [
        f"{sorted(r.methods)} {r.path}"
        for r in client.app.routes  # type: ignore[attr-defined]
        if isinstance(r, APIRoute)
        and r.path.startswith("/api")
        and r.path not in public
        and not uses_principal(r.dependant)
    ]
    assert missing == []
