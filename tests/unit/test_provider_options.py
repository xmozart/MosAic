"""S22's models-by-task table: options per provider and Reset of a task's choice."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mosaic.app.main import create_app
from mosaic.app.services import Services
from mosaic.storage.control import ControlDB


def _client() -> TestClient:
    app = create_app(Services.create(ControlDB()))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


def test_options_list_providers_their_tasks_models_and_presets() -> None:
    o = _client().get("/api/providers/options").json()
    assert o["capabilities"][:2] == ["vision", "planner"]
    assert "fake" not in o["providers"]
    anthropic = o["providers"]["anthropic"]
    assert anthropic["mode"] == "cloud"
    assert "claude-sonnet-5-5" in anthropic["models"]
    assert anthropic["fixed_models"] is False
    assert "transcriber" not in anthropic["capabilities"]
    whisper = o["providers"]["faster-whisper"]
    assert whisper == {
        "mode": "local",
        "capabilities": ["transcriber"],
        "models": ["small", "medium", "large-v3"],
        "fixed_models": True,
    }
    assert o["providers"]["claude-cli"]["mode"] == "cli"
    assert o["presets"]["codex-cli"]["planner"] == "gpt-5.5"


def test_a_task_choice_resets_to_the_default() -> None:
    client = _client()
    r = client.patch(
        "/api/providers", json={"planner": {"provider": "claude-cli", "model": "claude-sonnet-5-5"}}
    )
    assert r.status_code == 200
    assert r.json()["planner"]["source"] == "user"
    assert r.json()["planner"]["provider"] == "claude-cli"
    r = client.patch("/api/providers", json={"planner": None})
    assert r.json()["planner"]["source"] == "default"
    assert r.json()["planner"]["provider"] == "anthropic"
    assert client.patch("/api/providers", json={"nonsense": None}).status_code == 422
    bad = client.patch(
        "/api/providers", json={"transcriber": {"provider": "faster-whisper", "model": "huge"}}
    )
    assert bad.status_code == 422
