"""Media roots and the server folder browser; M2 acceptance 2: path traversal, symlink
escape and absolute-path requests are rejected (ADR 0035)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    """A media root with trips, a project, a hidden folder and an escaping symlink; a
    secret folder outside it."""
    root = tmp_path / "media"
    trip = root / "Costa Rica 2026"
    (trip / "Day 1").mkdir(parents=True)
    (trip / "GX010001.MP4").write_bytes(b"x")
    (trip / "IMG_0001.HEIC").write_bytes(b"x")
    (trip / "notes.txt").write_text("x")
    (root / "Iceland").mkdir()
    (root / "Iceland" / ".mosaic-project.json").write_text("{}")
    (root / ".hidden").mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "passwords").mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "inside-link").symlink_to(root / "Iceland", target_is_directory=True)
    return {"root": root, "trip": trip, "outside": outside}


def _signed_in(
    monkeypatch: pytest.MonkeyPatch, mode: str = "server"
) -> tuple[TestClient, dict[str, str]]:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    monkeypatch.setenv("MOSAIC_MODE", mode)
    app = create_app(Services.create(ControlDB()))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app, base_url="https://testserver")
    headers: dict[str, str] = {}
    if mode == "server":
        csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]
        headers = {"X-CSRF-Token": csrf}
    return client, headers


def _add_root(client: TestClient, headers: dict[str, str], path: Path) -> int:
    r = client.post(
        "/api/admin/media-roots", json={"path": str(path), "label": "Media"}, headers=headers
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_admin_manages_roots(tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    items = client.get("/api/admin/media-roots").json()["items"]
    assert [(i["id"], i["label"]) for i in items] == [(rid, "Media")]
    for bad in ("relative/path", str(tree["root"] / "missing")):
        r = client.post("/api/admin/media-roots", json={"path": bad}, headers=h)
        assert r.status_code == 422, bad
    assert client.delete(f"/api/admin/media-roots/{rid}", headers=h).status_code == 204
    assert client.get("/api/admin/media-roots").json()["items"] == []


def test_browse_lists_folders_with_counts(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    top = client.get("/api/fs/browse").json()
    assert top["roots"] == [{"id": rid, "label": "Media", "source": "admin"}], "no server paths"
    body = client.get("/api/fs/browse", params={"root": rid}).json()
    names = [i["name"] for i in body["items"]]
    assert names == ["Costa Rica 2026", "Iceland", "inside-link"], (
        "hidden and escaping entries left out"
    )
    by = {i["name"]: i for i in body["items"]}
    # Recursive: the trip's own two files plus nothing in "Day 1"; one sub-folder.
    assert by["Costa Rica 2026"]["counts"] == {
        "videos": 1,
        "photos": 1,
        "folders": 1,
        "complete": True,
    }
    assert by["Iceland"]["has_project"] is True
    assert by["inside-link"]["path"] == "Iceland", "paths are canonical, relative to the root"
    trip = client.get("/api/fs/browse", params={"root": rid, "path": "Costa Rica 2026"}).json()
    assert trip["crumbs"] == [
        {"name": "Media", "path": ""},
        {"name": "Costa Rica 2026", "path": "Costa Rica 2026"},
    ]
    assert trip["here"] == {
        "counts": {"videos": 1, "photos": 1, "folders": 1, "complete": True},
        "has_project": False,
    }
    assert [i["name"] for i in trip["items"]] == ["Day 1"]
    text = str(body) + str(trip)
    assert str(tree["root"]) not in text, "clients never see the server's absolute paths"


@pytest.mark.parametrize(
    "path",
    [
        "..",
        "../secret",
        "../../",
        "Costa Rica 2026/../../secret",
        "escape",
        "escape/passwords",
        "/etc",
        "//etc/passwd",
        "C:\\Windows",
        "..\\secret",
        "Costa Rica 2026/\x00",
    ],
)
def test_traversal_symlink_and_absolute_paths_are_refused(
    path: str, tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    r = client.get("/api/fs/browse", params={"root": rid, "path": path})
    assert r.status_code in (403, 404), (path, r.status_code)
    assert "passwords" not in r.text
    assert str(tree["outside"]) not in r.text


def test_encoded_traversal_in_the_raw_query(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    for raw in ("%2e%2e%2fsecret", "..%2fsecret", "%2e%2e/%2e%2e/etc"):
        r = client.get(f"/api/fs/browse?root={rid}&path={raw}")
        assert r.status_code in (403, 404), raw
        assert "passwords" not in r.text


def test_unknown_root_and_desktop_mode(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _signed_in(monkeypatch)
    assert client.get("/api/fs/browse", params={"root": 999}).status_code == 404
    desktop, _ = _signed_in(monkeypatch, "desktop")
    assert desktop.get("/api/fs/browse").status_code == 404
    assert desktop.get("/api/admin/media-roots").status_code == 404


def test_relink_to_a_folder_outside_the_roots_is_refused(
    tree: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.storage.projects import init_project

    client, h = _signed_in(monkeypatch)
    _add_root(client, h, tree["root"])
    svc = client.app.state.services  # type: ignore[attr-defined]
    project = init_project(svc.control, svc.principal, tree["trip"])
    pid = project.id
    project.close()
    for target in (str(tree["outside"]), str(tree["root"] / "escape"), "/etc"):
        r = client.post(f"/api/projects/{pid}/relink", json={"choose_folder": target}, headers=h)
        assert r.status_code == 403, (target, r.status_code, r.text)


def test_roots_from_the_environment(tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAIC_MEDIA_ROOTS", os.pathsep.join([str(tree["root"]), "/no/such/mount"]))
    client, _ = _signed_in(monkeypatch)
    roots = client.get("/api/admin/media-roots").json()["items"]
    assert [(r["path"], r["source"]) for r in roots] == [(str(tree["root"].resolve()), "env")]


def test_unreadable_and_overlong_entries_do_not_break_browsing(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    locked = tree["root"] / "Locked"
    locked.mkdir()
    (locked / "inner").mkdir()
    locked.chmod(0)
    try:
        r = client.get("/api/fs/browse", params={"root": rid})
        assert r.status_code == 200
        names = [i["name"] for i in r.json()["items"]]
        assert "Costa Rica 2026" in names, "siblings are still listed"
        inside = client.get("/api/fs/browse", params={"root": rid, "path": "Locked"})
        assert inside.status_code in (403, 404)
    finally:
        locked.chmod(0o755)
    for path in ("ok/" + "a" * 300, "/".join(["x"] * 2000)):
        assert client.get("/api/fs/browse", params={"root": rid, "path": path}).status_code == 404


def test_lut_files_outside_the_roots_are_refused(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from mosaic.storage.models_project import Device
    from mosaic.storage.projects import init_project

    client, h = _signed_in(monkeypatch)
    _add_root(client, h, tree["root"])
    cube = "LUT_3D_SIZE 2\n" + "0 0 0\n" * 8
    (tree["outside"] / "evil.cube").write_text(cube)
    (tree["trip"] / "ok.cube").write_text(cube)
    svc = client.app.state.services  # type: ignore[attr-defined]
    project = init_project(svc.control, svc.principal, tree["trip"])
    with project.write() as s:
        s.add(Device(key="cam", label="Cam"))
    with project.db.session() as s:
        did = s.scalar(select(Device.id))
    pid = project.id
    project.close()
    url = f"/api/projects/{pid}/devices"
    for bad in (str(tree["outside"] / "evil.cube"), str(tree["root"] / "escape" / "evil.cube")):
        r = client.put(url, json={"devices": [{"id": did, "lut_path": bad}]}, headers=h)
        assert r.status_code == 403, (bad, r.status_code, r.text)
        assert str(tree["outside"]) not in r.text
    ok = client.put(
        url, json={"devices": [{"id": did, "lut_path": str(tree["trip"] / "ok.cube")}]}, headers=h
    )
    assert ok.status_code == 200, ok.text


def test_server_relink_answers_with_relative_paths(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.storage.projects import init_project

    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    svc = client.app.state.services  # type: ignore[attr-defined]
    project = init_project(svc.control, svc.principal, tree["trip"])
    pid = project.id
    project.close()
    r = client.post(f"/api/projects/{pid}/relink", json={}, headers=h)
    assert r.status_code == 202, r.text
    assert r.json()["root"] == {"root": rid, "path": "Costa Rica 2026"}
    assert str(tree["root"]) not in r.text


def test_counts_are_recursive_capped_and_budgeted(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.app.routers import files

    for i in range(3):
        (tree["trip"] / "Day 1" / f"GX01000{i}.MP4").write_bytes(b"x")
    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    by = {i["name"]: i for i in client.get("/api/fs/browse", params={"root": rid}).json()["items"]}
    assert by["Costa Rica 2026"]["counts"]["videos"] == 4, "files in sub-folders count"
    monkeypatch.setattr(files, "FOLDER_ENTRIES", 2)
    by = {i["name"]: i for i in client.get("/api/fs/browse", params={"root": rid}).json()["items"]}
    assert by["Costa Rica 2026"]["counts"]["complete"] is False
    monkeypatch.setattr(files, "BROWSE_BUDGET_S", -1.0)
    items = client.get("/api/fs/browse", params={"root": rid}).json()["items"]
    assert all(i["counts"] is None for i in items), "past the budget: listed without counts"


def test_a_count_walk_stops_at_its_deadline(tree: dict[str, Path]) -> None:
    import time

    from mosaic.media.scan import quick_counts

    for i in range(600):
        (tree["trip"] / f"IMG_{i:04d}.JPG").write_bytes(b"x")
    full = quick_counts(tree["root"], 20_000)
    assert full["complete"] is True
    assert full["photos"] >= 600
    stopped = quick_counts(tree["root"], 20_000, deadline=time.monotonic() - 1)
    assert stopped["complete"] is False, "a slow share stops the walk; the count is a lower bound"
    assert stopped["photos"] < full["photos"]


def test_server_relink_by_root_and_path(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from mosaic.storage.projects import init_project

    client, h = _signed_in(monkeypatch)
    rid = _add_root(client, h, tree["root"])
    svc = client.app.state.services  # type: ignore[attr-defined]
    project = init_project(svc.control, svc.principal, tree["trip"])
    pid = project.id
    project.close()
    moved = tree["root"] / "Moved trip"
    shutil.move(str(tree["trip"]), str(moved))
    r = client.post(
        f"/api/projects/{pid}/relink", json={"root": rid, "path": "Moved trip"}, headers=h
    )
    assert r.status_code == 202, r.text
    assert r.json()["root"] == {"root": rid, "path": "Moved trip"}
    both = client.post(
        f"/api/projects/{pid}/relink",
        json={"root": rid, "path": "Moved trip", "choose_folder": str(moved)},
        headers=h,
    )
    assert both.status_code == 422
    out = client.post(
        f"/api/projects/{pid}/relink", json={"root": rid, "path": "../secret"}, headers=h
    )
    assert out.status_code == 403


def test_roots_from_the_environment_take_commas_or_colons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.storage import media_roots
    from mosaic.storage.control import ControlDB

    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv(
        "MOSAIC_MEDIA_ROOTS", f"{tmp_path / 'a'},{tmp_path / 'b'}:{tmp_path / 'c'}, /missing"
    )
    control = ControlDB()
    media_roots.seed_from_env(control)
    assert sorted(r.path.name for r in media_roots.roots(control)) == ["a", "b", "c"]
