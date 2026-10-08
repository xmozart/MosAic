"""Server secret backends: encrypted file with a master key, Docker secrets, environment
(M2 step 3c; ARCHITECTURE.md §3; ADR 0036). Keys are write-only everywhere."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"
KEY = "sk-ant-api03-ServerSecretValue-WXYZ"
MASTER = "m" * 40


def _signed_in(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, str]]:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_MODE", "server")
    app = create_app(Services.create(ControlDB()))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app, base_url="https://testserver")
    csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]
    return client, {"X-CSRF-Token": csrf}


def _key(client: TestClient) -> dict[str, object]:
    providers = client.get("/api/providers").json()
    return dict(providers["vision"]["key"])


def _app_data_bytes() -> bytes:
    from mosaic.core.paths import app_data_dir

    out = b""
    for p in app_data_dir().rglob("*"):
        if p.is_file():
            out += p.read_bytes()
    return out


@pytest.fixture(autouse=True)
def docker_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "run-secrets"
    d.mkdir()
    monkeypatch.setenv("MOSAIC_DOCKER_SECRETS_DIR", str(d))
    monkeypatch.delenv("MOSAIC_MASTER_KEY", raising=False)
    monkeypatch.delenv("MOSAIC_MASTER_KEY_FILE", raising=False)
    monkeypatch.delenv("MOSAIC_SECRET_AI_ANTHROPIC", raising=False)
    return d


def test_saving_a_key_needs_the_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client, h = _signed_in(monkeypatch)
    client.patch(
        "/api/providers",
        json={"vision": {"provider": "anthropic", "model": "claude-haiku-4-5"}},
        headers=h,
    )
    r = client.put("/api/secrets/ai/anthropic", json={"value": KEY}, headers=h)
    assert r.status_code == 422
    assert "MOSAIC_MASTER_KEY" in r.json()["detail"]
    assert KEY not in r.text
    assert _key(client)["configured"] is False


def test_encrypted_file_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.core.paths import app_data_dir

    monkeypatch.setenv("MOSAIC_MASTER_KEY", MASTER)
    client, h = _signed_in(monkeypatch)
    client.patch(
        "/api/providers",
        json={"vision": {"provider": "anthropic", "model": "claude-haiku-4-5"}},
        headers=h,
    )
    r = client.put("/api/secrets/ai/anthropic", json={"value": KEY}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "configured": True,
        "last4": "WXYZ",
        "store": "encrypted_file",
        "from_deployment": False,
    }
    store = app_data_dir() / "secrets.enc.json"
    assert stat.S_IMODE(store.stat().st_mode) == 0o600
    assert KEY.encode() not in _app_data_bytes(), "nowhere in app data in plain text"
    assert _key(client)["last4"] == "WXYZ"

    from mosaic.storage.config import ConfigService

    svc = client.app.state.services  # type: ignore[attr-defined]
    assert ConfigService(svc.control).key_for(svc.principal, "anthropic") == KEY

    monkeypatch.setenv("MOSAIC_MASTER_KEY", "x" * 40)  # the master key changed
    status = ConfigService(svc.control).key_status(svc.principal, "anthropic")
    assert status.configured is False
    assert status.error
    assert "master key changed" in status.error


def test_master_key_from_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "master"
    f.write_text(MASTER + "\n")
    monkeypatch.setenv("MOSAIC_MASTER_KEY_FILE", str(f))
    client, h = _signed_in(monkeypatch)
    r = client.put("/api/secrets/ai/anthropic", json={"value": KEY}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["store"] == "encrypted_file"


def test_deployment_keys_docker_then_env_and_user_override(
    docker_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOSAIC_MASTER_KEY", MASTER)
    monkeypatch.setenv("MOSAIC_SECRET_AI_ANTHROPIC", "sk-from-env-ENVV")
    client, h = _signed_in(monkeypatch)
    client.patch(
        "/api/providers",
        json={"vision": {"provider": "anthropic", "model": "claude-haiku-4-5"}},
        headers=h,
    )
    assert _key(client) == {
        "configured": True,
        "last4": "ENVV",
        "store": "environment",
        "from_deployment": True,
    }
    (docker_dir / "mosaic_ai_anthropic").write_text("sk-from-docker-DOCK\n")
    assert _key(client) == {
        "configured": True,
        "last4": "DOCK",
        "store": "docker",
        "from_deployment": True,
    }
    # A key the user enters overrides the deployment's; resetting it falls back.
    client.put("/api/secrets/ai/anthropic", json={"value": KEY}, headers=h)
    assert _key(client)["last4"] == "WXYZ"
    assert client.delete("/api/secrets/ai/anthropic", headers=h).status_code in (200, 204)
    assert _key(client)["last4"] == "DOCK"
    text = str(client.get("/api/providers").json())
    for secret in ("sk-from-env-ENVV", "sk-from-docker-DOCK", KEY):
        assert secret not in text


def test_deployment_refs_are_read_only() -> None:
    from mosaic.storage import secrets

    for ref in ("env:MOSAIC_SECRET_AI_ANTHROPIC", "docker:mosaic_ai_anthropic"):
        with pytest.raises(secrets.SecretError, match="read-only"):
            secrets.store(ref, "value-1234")
    with pytest.raises(secrets.SecretError):
        secrets.load("docker:../../etc/passwd")
    assert os.sep not in secrets.docker_name("ai/anthropic")


def test_concurrent_saves_keep_every_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from mosaic.storage import secrets

    monkeypatch.setenv("MOSAIC_MODE", "server")
    monkeypatch.setenv("MOSAIC_MASTER_KEY", MASTER)
    names = [f"ai/p{i}" for i in range(8)]
    errors: list[BaseException] = []

    def save(name: str) -> None:
        try:
            secrets.store(secrets.file_ref(name), f"value-for-{name}-1234")
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    for n in names:
        assert secrets.load(secrets.file_ref(n)) == f"value-for-{n}-1234"


def test_a_damaged_key_file_is_reported_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.core.paths import app_data_dir

    monkeypatch.setenv("MOSAIC_MASTER_KEY", MASTER)
    client, h = _signed_in(monkeypatch)
    client.patch(
        "/api/providers",
        json={"vision": {"provider": "anthropic", "model": "claude-haiku-4-5"}},
        headers=h,
    )
    client.put("/api/secrets/ai/anthropic", json={"value": KEY}, headers=h)
    store = app_data_dir() / "secrets.enc.json"
    for damage in ('{"version": 1, "entries"', '{"version": 1}', '{"salt": "!!", "entries": {}}'):
        store.write_text(damage)
        r = client.get("/api/providers")
        assert r.status_code == 200, damage
        assert r.json()["vision"]["key"]["configured"] is False
        assert damage not in r.text
        # Entering the key again (as the message says) works: the damaged file is kept
        # aside and a fresh store is started.
        again = client.put("/api/secrets/ai/anthropic", json={"value": KEY}, headers=h)
        assert again.status_code == 200, again.text
        assert client.get("/api/providers").json()["vision"]["key"]["last4"] == "WXYZ"
    kept = list(store.parent.glob("secrets.enc.json.damaged-*"))
    assert len(kept) == 3, "every damaged file is kept, never deleted"


def test_installed_ai_apps_never_get_mosaic_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import sys

    from mosaic.ai.adapters import cli_common

    monkeypatch.setenv("MOSAIC_MASTER_KEY", MASTER)
    monkeypatch.setenv("MOSAIC_MASTER_KEY_FILE", "/run/secrets/master")
    monkeypatch.setenv("MOSAIC_SECRET_AI_ANTHROPIC", "sk-env-1234")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-drop")
    monkeypatch.setenv("HARMLESS", "kept")
    code = "import json, os; print(json.dumps(dict(os.environ)))"
    with cli_common.workdir() as cwd:
        out = cli_common.run(
            [sys.executable, "-c", code], "", Path(cwd), 30, drop_env=["ANTHROPIC_API_KEY"]
        )
    env = json.loads(out.stdout)
    assert env.get("HARMLESS") == "kept"
    for name in (
        "MOSAIC_MASTER_KEY",
        "MOSAIC_MASTER_KEY_FILE",
        "MOSAIC_SECRET_AI_ANTHROPIC",
        "ANTHROPIC_API_KEY",
    ):
        assert name not in env, name


def test_health_needs_no_sign_in_and_tells_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_MODE", "server")
    monkeypatch.setenv("MOSAIC_ALLOWED_HOSTS", "mosaic.example")
    client = TestClient(create_app(Services.create(ControlDB())), base_url="http://127.0.0.1:8765")
    r = client.get("/api/health")  # the container's own healthcheck, by loopback
    assert r.status_code == 200
    assert r.json() == {"ok": True}  # nothing else: no sign-in needed
    assert client.get("/api/system/info").status_code == 421, "everything else checks the host"


def test_health_is_unhealthy_when_the_control_db_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    client = TestClient(create_app(Services.create(control)), raise_server_exceptions=False)

    def broken() -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(control.db, "session", broken)
    assert client.get("/api/health").status_code == 500
