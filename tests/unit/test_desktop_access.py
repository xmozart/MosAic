"""Desktop API access: the shell's per-launch token (M3 acceptance 2; ADR 0057)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

TOKEN = "per-launch-token-for-tests-0123456789abcdef"
SAME = {"Sec-Fetch-Site": "same-origin"}


def _client(monkeypatch: pytest.MonkeyPatch, token: str | None = TOKEN) -> TestClient:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_MODE", "desktop")
    app = create_app(Services.create(ControlDB()), desktop_token=token)
    return TestClient(app, base_url="http://127.0.0.1:51234")


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_every_api_route_needs_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    # setup and login are server-only: in desktop mode they answer 404 and do nothing.
    public = {
        "/api/auth/status",
        "/api/auth/desktop-session",
        "/api/health",
        "/api/auth/setup",
        "/api/auth/login",
    }
    checked = 0
    for path, ops in client.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        if path in public:
            continue
        url = path.replace("{ref}", "ai/anthropic")
        for part in ("{pid}", "{eid}", "{job_id}", "{version}", "{aid}", "{rid}", "{tid}"):
            url = url.replace(part, "1")
        for method in ops:
            r = client.request(method.upper(), url, json={})
            assert r.status_code == 401, (method, path, r.status_code)
            r = client.request(method.upper(), url, json={}, headers=_bearer("wrong"))
            assert r.status_code == 401, (method, path, "wrong token")
            checked += 1
    assert checked > 60
    assert client.get("/api/jobs", headers=_bearer()).status_code == 200
    assert client.get("/api/health").json() == {"ok": True}
    for path in ("/api/auth/setup", "/api/auth/login"):
        assert client.post(path, json={"password": "x" * 12}).status_code == 404


def test_the_token_becomes_a_same_origin_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    assert client.get("/api/auth/status").json()["signed_in"] is False
    assert client.post("/api/auth/desktop-session").status_code == 401
    assert client.post("/api/auth/desktop-session", headers=_bearer("wrong")).status_code == 401
    r = client.post("/api/auth/desktop-session", headers=_bearer())
    assert r.status_code == 200
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("mosaic_desktop="))
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower()
    assert TOKEN not in cookie, "the cookie is a session, not the token"
    # The webview's own requests: same origin.
    assert client.get("/api/jobs", headers=SAME).status_code == 200
    assert client.get("/api/auth/status", headers=SAME).json()["signed_in"] is True
    # Another page on 127.0.0.1 (another port is the same *site*, so it gets the cookie),
    # or a client that can't say where it comes from: refused.
    for site in ("same-site", "cross-site"):
        assert client.get("/api/jobs", headers={"Sec-Fetch-Site": site}).status_code == 401
        assert (
            client.post("/api/jobs/1/cancel", headers={"Sec-Fetch-Site": site}).status_code == 401
        )
    assert client.get("/api/jobs").status_code == 401


def test_only_loopback_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    for host in ("evil.example", "127.0.0.1.nip.io", "192.168.1.5"):
        r = client.get("/api/jobs", headers={**_bearer(), "Host": host})
        assert r.status_code == 421, host
    assert (
        client.get("/api/jobs", headers={**_bearer(), "Host": "localhost:51234"}).status_code == 200
    )


def test_no_cors_for_any_other_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    pre = client.options(
        "/api/jobs",
        headers={"Origin": "http://127.0.0.1:9999", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in pre.headers}
    r = client.get("/api/jobs", headers={**_bearer(), "Origin": "http://127.0.0.1:9999"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_the_token_leaves_the_environment_before_workers_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mosaic.app.desktop import ENV_TOKEN, take_token_from_env
    from mosaic.core.runtime import scrubbed_env

    monkeypatch.setenv(ENV_TOKEN, TOKEN)
    assert ENV_TOKEN not in scrubbed_env(), "never handed to FFmpeg or AI apps"
    assert take_token_from_env() == TOKEN
    assert ENV_TOKEN not in os.environ, "workers copy os.environ; the token is gone"


def test_without_a_token_desktop_mode_is_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`mosaic serve` for developers and the test suite (ADR 0057)."""
    client = _client(monkeypatch, token=None)
    assert client.get("/api/jobs").status_code == 200
    assert client.post("/api/auth/desktop-session").status_code == 404
    assert client.get("/api/jobs", headers={"Host": "evil.example"}).status_code == 421


@pytest.mark.parametrize("value", ["", "   ", "short", "é" * 40])
def test_a_set_but_unusable_token_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A shell bug that passes an empty token must not mean "no protection"."""
    import io

    from mosaic.app.desktop import ENV_TOKEN, DesktopTokenError, read_token, take_token_from_env

    monkeypatch.setenv(ENV_TOKEN, value)
    with pytest.raises(DesktopTokenError):
        take_token_from_env()
    with pytest.raises(DesktopTokenError):
        read_token(io.StringIO(value + "\n"))


def test_non_ascii_credentials_are_refused_not_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    r = client.get("/api/jobs", headers={"Authorization": "Bearer été".encode("latin-1")})  # type: ignore[dict-item]
    assert r.status_code == 401
