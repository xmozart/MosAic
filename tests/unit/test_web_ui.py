"""The web UI served by the API (M2 step 1) and the generated client's schema (M2
acceptance 9)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]


def _client(ui: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_UI_DIR", str(ui))
    app = create_app(Services.create(ControlDB()))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


@pytest.fixture
def ui(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>MosAic</title>")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside")
    return root


def test_spa_routes_assets_and_api(ui: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(ui, monkeypatch)
    for path in ("/", "/library", "/projects/abc/library?group=day"):
        r = client.get(path)
        assert r.status_code == 200
        assert "<title>MosAic</title>" in r.text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    r = client.get("/api/no-such-endpoint")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert client.get("/api/system/info").status_code == 200


def test_no_file_outside_the_ui_folder(ui: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (ui / "link.txt").symlink_to(ui.parent / "secret.txt")  # a symlink escaping the folder
    client = _client(ui, monkeypatch)
    for path in (
        "/%2e%2e/secret.txt",
        "/%2e%2e%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/link.txt",
        f"/{ui.parent / 'secret.txt'}",  # an absolute path
        "//etc/passwd",
    ):
        r = client.get(path)
        assert "outside" not in r.text, path
        assert "root:" not in r.text, path


def test_unknown_api_paths_are_json_404_for_every_method(
    ui: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(ui, monkeypatch)
    for method in ("GET", "POST", "PUT", "DELETE"):
        r = client.request(method, "/api/no-such-endpoint")
        assert r.status_code == 404, method
        assert r.headers["content-type"].startswith("application/json")
    assert client.post("/library").status_code == 405


def test_no_ui_folder_means_api_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path / "missing", monkeypatch)
    assert client.get("/").status_code == 404


def test_generated_openapi_is_current() -> None:
    """The committed document the frontend client is generated from matches the API
    (regenerate with `npm run api` in frontend/)."""
    from mosaic.app.openapi_export import render

    committed = REPO / "frontend" / "src" / "api" / "openapi.json"
    assert committed.read_text() == render(), "run `npm run api` in frontend/"
