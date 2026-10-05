"""Project leases and read-only open (M1 step 7, ADR 0023)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mosaic.storage import lease
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import ProjectMeta
from mosaic.storage.projects import ReadOnlyProjectError, init_project, open_project


def _other(folder: Path, *, minutes: int = 5, host: str = "other-mac") -> None:
    """Another installation's lease, valid for ``minutes`` (negative: expired)."""
    now = datetime.now(UTC)
    (folder / lease.LEASE_FILE).write_text(
        json.dumps(
            {
                "holder": "OTHER-INSTALLATION",
                "host": host,
                "pid": 1,
                "acquired_at": now.isoformat(timespec="seconds"),
                "expires_at": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
            }
        )
    )


def test_acquire_renew_release(tmp_path: Path) -> None:
    a = lease.acquire(tmp_path, "me")
    assert a.holder == "me"
    assert not a.expired()
    assert lease.acquire(tmp_path, "me") == a, "a recent lease is not rewritten"
    assert lease.renew(tmp_path, "me")
    lease.release(tmp_path, "someone-else")
    assert lease.read(tmp_path) is not None, "only the holder releases"
    lease.release(tmp_path, "me")
    assert lease.read(tmp_path) is None


def test_live_lease_of_another_installation(tmp_path: Path) -> None:
    _other(tmp_path)
    with pytest.raises(lease.LeaseHeldError) as err:
        lease.acquire(tmp_path, "me")
    assert "other-mac" in str(err.value)
    assert not lease.renew(tmp_path, "me"), "a taken-over lease is lost, not renewed"
    taken = lease.acquire(tmp_path, "me", force=True)
    assert taken.holder == "me"


def test_expired_lease_is_taken_over(tmp_path: Path) -> None:
    _other(tmp_path, minutes=-1)
    assert lease.acquire(tmp_path, "me").holder == "me"


def test_projects_take_the_lease_and_read_only_never_does(tmp_path: Path) -> None:
    control = ControlDB()
    me = control.local_principal
    p = init_project(control, me, tmp_path)
    held = lease.read(p.outputs_dir)
    assert held is not None
    assert held.holder == control.installation_id
    p.close()
    _other(p.outputs_dir)
    with pytest.raises(lease.LeaseHeldError):
        open_project(control, me, tmp_path)
    ro = open_project(control, me, tmp_path, read_only=True)
    try:
        with ro.db.session() as s:
            assert s.get(ProjectMeta, "project_id") is not None, "reads work"
        with pytest.raises(ReadOnlyProjectError), ro.write() as s:
            s.add(ProjectMeta(key="x", value="1"))
        with pytest.raises(PermissionError):
            ro.artifacts.put_json("probe", "k" * 20, {}, provenance_id=1)
        assert ro.checkpoint() is None
    finally:
        ro.close()
    assert lease.read(p.outputs_dir).holder == "OTHER-INSTALLATION", "read-only took nothing"  # type: ignore[union-attr]
    taken = open_project(control, me, tmp_path, take_over=True)
    assert lease.read(taken.outputs_dir).holder == control.installation_id  # type: ignore[union-attr]
    taken.close()


def test_api_open_close_and_lock_lost(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    pid, out = p.id, p.outputs_dir
    p.close()
    lease.release(out, control.installation_id)
    svc = Services.create(control)
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    base = f"/api/projects/{pid}"

    r = client.post(f"{base}/open")
    assert r.status_code == 200, r.text
    assert r.json()["read_only"] is False
    assert lease.read(out).holder == control.installation_id  # type: ignore[union-attr]
    # Another computer takes it over: the next renewal loses it, the project turns read-only.
    _other(out)
    svc.leases.renew_all()
    assert pid in svc.leases.lost
    r = client.put(f"{base}/trip-context", json={"trip_name": "x"})
    assert r.status_code == 409, "writes are refused once the lease is lost"
    events = client.get("/api/events", params={"project": pid, "until_idle": True})
    assert "event: lock.lost" in events.text
    # Opening again: 409 with the holder for the S0 dialog; read-only works.
    r = client.post(f"{base}/open")
    assert r.status_code == 409
    assert r.json()["holder"]["host"] == "other-mac"
    r = client.post(f"{base}/open", json={"read_only": True})
    assert r.status_code == 200
    assert client.get(f"{base}/trip-context").status_code == 200
    r = client.post(f"{base}/open", json={"take_over": True})
    assert r.status_code == 200
    assert client.put(f"{base}/trip-context", json={"trip_name": "x"}).status_code == 200
    assert client.post(f"{base}/close").status_code == 200
    assert lease.read(out) is None, "close releases the lease"


def _client(control: ControlDB):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    svc = Services.create(control)
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    return svc, TestClient(app)


def test_read_only_refuses_jobs_and_reads_never_take_the_lease(tmp_path: Path) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    pid, out = p.id, p.outputs_dir
    p.close()
    _other(out)  # another computer is editing
    _svc, client = _client(control)
    base = f"/api/projects/{pid}"
    assert client.get(f"{base}/trip-context").status_code == 200, "a read takes no lease"
    assert client.get(f"{base}/edits").status_code == 200
    assert lease.read(out).holder == "OTHER-INSTALLATION"  # type: ignore[union-attr]
    assert client.post(f"{base}/open", json={"read_only": True}).status_code == 200
    for path, body in (
        ("analysis-runs", {"mode": "balanced"}),
        ("relink", {}),
        ("trip-context/parse", {"text": "notes"}),
        ("edits", {"duration_s": 30}),
    ):
        r = client.post(f"{base}/{path}", json=body)
        assert r.status_code == 409, (path, r.status_code, r.text)
    assert lease.read(out).holder == "OTHER-INSTALLATION"  # type: ignore[union-attr]


def test_relink_validates_the_chosen_folder(tmp_path: Path) -> None:
    control = ControlDB()
    trip = tmp_path / "trip"
    trip.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    p = init_project(control, control.local_principal, trip)
    q = init_project(control, control.local_principal, other)
    pid = p.id
    p.close()
    q.close()
    _svc, client = _client(control)
    url = f"/api/projects/{pid}/relink"
    assert client.post(url, json={"choose_folder": str(tmp_path / "nope")}).status_code == 422
    r = client.post(url, json={"choose_folder": str(other)})
    assert r.status_code == 422, "another project's folder"


def test_renewal_survives_errors_and_detects_a_lost_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    control = ControlDB()
    svc, _ = _client(control)
    monkeypatch.setattr(lease, "RENEW_AFTER_S", 0.02)
    calls: list[int] = []

    def flaky(_folder: Path, _holder: str) -> bool:
        calls.append(1)
        raise RuntimeError("unexpected")

    monkeypatch.setattr(lease, "renew", flaky)
    svc.leases.hold("P1", tmp_path)
    time.sleep(0.2)
    assert len(calls) >= 2, "the loop keeps running after an error"
    assert svc.leases._thread is not None
    assert svc.leases._thread.is_alive()
    monkeypatch.undo()
    _other(tmp_path)  # the read-back would show another holder
    svc.leases.renew_all()
    assert "P1" in svc.leases.lost
    svc.leases.shutdown()


def test_cli_lock(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from mosaic.cli.main import cli

    runner = CliRunner()
    assert runner.invoke(cli, ["init", str(tmp_path)]).exit_code == 0
    shown = runner.invoke(cli, ["lock", str(tmp_path)])
    assert "Held by this computer" in shown.output
    _other(tmp_path / "MosAic")
    held = runner.invoke(cli, ["context", "show", str(tmp_path)])
    assert held.exit_code == 0, "read-only commands work under a foreign lease"
    refused = runner.invoke(cli, ["context", "clear", str(tmp_path)])
    assert refused.exit_code != 0
    assert "other-mac" in refused.output
    assert "other-mac" in runner.invoke(cli, ["lock", str(tmp_path)]).output
    taken = runner.invoke(cli, ["lock", str(tmp_path), "--take-over"], input="y\n")
    assert taken.exit_code == 0, taken.output
    assert "now holds" in taken.output
    released = runner.invoke(cli, ["lock", str(tmp_path), "--release"])
    assert "Released" in released.output
    assert lease.read(tmp_path / "MosAic") is None
