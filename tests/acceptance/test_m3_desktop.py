"""M3 acceptance 2–5 (docs/milestones/M3.md) against the real backend process as the Mac
app runs it (`serve --port 0 --token-stdin`; ADR 0057, 0060). Acceptance 1 (a clean Mac)
is `make desktop-bundle`'s check and the desktop CI job (ADR 0061).

2. A second local web page cannot call the backend.
3. The API key persists across a restart through the OS keyring and appears in no file.
   The keyring is a file-backed stand-in outside MosAic's folders: tests never touch the
   owner's Keychain (Python keyring cannot be pointed at another keychain).
4. Force-quitting during analysis (SIGKILL of every process) and reopening resumes the
   job from the task log.
5. A project folder made on the desktop opens in server mode, and the reverse, with no
   migration.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.acceptance, pytest.mark.models]

TOKEN = "acceptance-desktop-token-0123456789abcdef"
CANARY = "sk-ant-api03-M3-CANARY-5d2c9e7a1b-NEVER-IN-A-FILE-WXYZ"
SERVE = [sys.executable, "-m", "mosaic.cli.main", "serve", "--port", "0", "--token-stdin"]
CLIPS = ("A001_basic.mp4", "A002_basic.mp4", "speech.mp4")


class Backend:
    def __init__(self, proc: subprocess.Popen[str], port: int) -> None:
        self.proc, self.port = proc, port
        self.base = f"http://127.0.0.1:{port}"

    def call(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        data = None if body is None else json.dumps(body).encode()
        h = {**({"Content-Type": "application/json"} if data else {}), **(headers or {})}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def ok(self, method: str, path: str, body: Any = None) -> Any:
        status, _, raw = self.call(method, path, body, {"Authorization": f"Bearer {TOKEN}"})
        assert status < 300, (method, path, status, raw[:300])
        return json.loads(raw) if raw else None

    def wait(self, job: int, timeout: float = 900) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.ok("GET", f"/api/jobs/{job}")["state"]
            if state in ("done", "failed", "cancelled"):
                return str(state)
            time.sleep(0.5)
        return "timeout"


@contextmanager
def backend(env: dict[str, str]) -> Iterator[Backend]:
    Path(env["MOSAIC_HOME"]).parent.mkdir(parents=True, exist_ok=True)
    log = (Path(env["MOSAIC_HOME"]).parent / "serve.log").open("a")
    proc = subprocess.Popen(
        SERVE,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        # The backend's log, next to its app data: the key test scans it too.
        stderr=log,
        text=True,
        env=env,
        start_new_session=True,  # its own group: a force-quit can kill the whole tree
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(TOKEN + "\n")
    proc.stdin.flush()
    port = None
    deadline = time.monotonic() + 120
    while port is None and time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line.startswith("MOSAIC_READY port="):
            port = int(line.split("=", 1)[1])
        elif not line and proc.poll() is not None:
            raise AssertionError(f"serve exited ({proc.returncode})")
    assert port
    try:
        yield Backend(proc, port)
    finally:
        if proc.poll() is None:
            proc.stdin.close()  # the lifeline: a graceful stop
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.close()


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOSAIC_DESKTOP")}
    env.update({"MOSAIC_MODE": "desktop", "MOSAIC_HOME": str(tmp / "home"), **extra})
    return env


def _trip(corpus_dir: Path, tmp: Path, name: str = "Trip") -> Path:
    trip = tmp / name
    trip.mkdir()
    for clip in CLIPS:
        shutil.copy2(corpus_dir / clip, trip / clip)
    return trip


# ------------------------------------------------------------------ 2


def test_a_second_local_page_cannot_call_the_backend(tmp_path: Path) -> None:
    with backend(_env(tmp_path)) as b:
        # The app's own webview: its session cookie with Sec-Fetch-Site: same-origin.
        status, headers, _ = b.call(
            "POST", "/api/auth/desktop-session", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert status == 200
        cookie = headers["set-cookie"].split(";", 1)[0]
        assert (
            b.call("GET", "/api/jobs", headers={"Cookie": cookie, "Sec-Fetch-Site": "same-origin"})[
                0
            ]
            == 200
        )
        # Another page can't mint a session of its own, nor use the cookie without the
        # browser saying where the request comes from.
        mint = b.call(
            "POST", "/api/auth/desktop-session", headers={"Origin": "http://127.0.0.1:9999"}
        )
        assert mint[0] == 401
        assert b.call("GET", "/api/jobs", headers={"Cookie": cookie})[0] == 401
        # Another page on this computer: 127.0.0.1 on another port is the same *site*, so
        # a browser would send the cookie, but Sec-Fetch-Site says it isn't this origin.
        other = {"Cookie": cookie, "Origin": "http://127.0.0.1:9999"}
        for site in ("same-site", "cross-site"):
            for method, path in (
                ("GET", "/api/jobs"),
                ("POST", "/api/jobs/pause-all"),
                ("GET", "/api/settings"),
            ):
                assert b.call(method, path, headers={**other, "Sec-Fetch-Site": site})[0] == 401, (
                    site,
                    path,
                )
        # Without the token or the cookie, nothing; and no CORS header for anyone.
        status, headers, _ = b.call("GET", "/api/jobs", headers={"Origin": "http://localhost:3000"})
        assert status == 401
        assert not any(k.lower().startswith("access-control-") for k in headers)
        # DNS rebinding: a hostile name that resolves to 127.0.0.1.
        assert (
            b.call(
                "GET",
                "/api/jobs",
                headers={"Authorization": f"Bearer {TOKEN}", "Host": "evil.example"},
            )[0]
            == 421
        )


# ------------------------------------------------------------------ 3


def test_the_key_persists_through_the_keyring_and_is_in_no_file(tmp_path: Path) -> None:
    keychain = tmp_path / "os-keychain.json"  # stands in for the macOS Keychain
    env = _env(
        tmp_path,
        PYTHON_KEYRING_BACKEND="tests.support.testkeyring.FileKeyring",
        TEST_KEYRING_FILE=str(keychain),
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
    )
    with backend(env) as b:
        b.ok("PUT", "/api/secrets/ai/anthropic", {"value": CANARY})
        assert "WXYZ" in json.dumps(b.ok("GET", "/api/providers"))
    with backend(env) as b:  # a restart: a new process, a new token session
        providers = b.ok("GET", "/api/providers")
        assert "WXYZ" in json.dumps(providers), "the key is still configured"
        assert CANARY not in json.dumps(providers)
    assert CANARY in keychain.read_text(), "it lives in the keyring"
    needles = (CANARY.encode(), CANARY[:-4].encode())
    leaks = [  # app data, its logs and the backend's own log; not the keyring itself
        str(p)
        for p in tmp_path.rglob("*")
        if p.is_file() and p != keychain and any(n in p.read_bytes() for n in needles)
    ]
    assert (tmp_path / "serve.log").stat().st_size > 0, "the log was captured and scanned"
    assert not leaks, f"the key leaked into {leaks}"


# ------------------------------------------------------------------ 4


def test_force_quit_during_analysis_resumes_from_the_task_log(
    corpus_dir: Path, tmp_path: Path
) -> None:
    env = _env(tmp_path, MOSAIC_LEASE_MS="5000")
    trip = _trip(corpus_dir, tmp_path)
    with backend(env) as b:
        b.ok("PATCH", "/api/providers", {"all": {"provider": "fake", "model": "fake"}})
        made = b.ok("POST", "/api/projects", {"path": str(trip)})
        assert b.wait(made["scan_job"]) == "done"
        job = b.ok(
            "POST",
            f"/api/projects/{made['id']}/analysis-runs",
            {"mode": "quick", "cost_limit": 1.0},
        )["job_id"]
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            p = b.ok("GET", f"/api/jobs/{job}")["progress"] or {}
            if p.get("done", 0) >= 3:
                break
            time.sleep(0.2)
        assert b.ok("GET", f"/api/jobs/{job}")["state"] == "running", "killed mid-analysis"
        # Force quit: SIGKILL to the backend and every worker, no clean-up of any kind.
        workers = _worker_pids(tmp_path / "home")
        os.killpg(b.proc.pid, signal.SIGKILL)
        for pid in workers:
            _kill(pid)
        b.proc.wait(timeout=30)
    # Everything is dead, so this is exactly what the kill interrupted.
    before = _tasks(tmp_path / "home", job)
    done_before = {tid: t for tid, t in before.items() if t["status"] == "done"}
    open_before = {tid for tid, t in before.items() if t["status"] not in ("done", "skipped")}
    assert done_before, "some work had finished"
    assert open_before, "and some had not: the kill came mid-analysis"
    with backend(env) as b:  # reopen
        assert b.wait(job, timeout=900) == "done", "the job resumed and finished"
    after = _tasks(tmp_path / "home", job)
    for tid, t in done_before.items():  # resumed from the task log, not run again
        assert after[tid]["finished_at"] == t["finished_at"], tid
        assert after[tid]["attempts"] == t["attempts"], tid
    assert all(after[tid]["status"] in ("done", "skipped") for tid in open_before)
    assert not [t for t in after.values() if t["status"] == "failed"]


def _tasks(home: Path, job: int) -> dict[int, dict[str, Any]]:
    import sqlite3

    db = sqlite3.connect(f"file:{home / 'control.db'}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT id, status, finished_at, attempts FROM task WHERE job_id = ?", (job,)
        ).fetchall()
    finally:
        db.close()
    return {r[0]: {"status": r[1], "finished_at": r[2], "attempts": r[3]} for r in rows}


def _worker_pids(home: Path) -> list[int]:
    import sqlite3

    db = sqlite3.connect(f"file:{home / 'control.db'}?mode=ro", uri=True)
    try:
        return [int(r[0]) for r in db.execute("SELECT pid FROM worker")]
    finally:
        db.close()


def _kill(pid: int) -> None:
    with contextlib.suppress(OSError):
        os.killpg(pid, signal.SIGKILL)  # a worker leads its own group


# ------------------------------------------------------------------ 5


def test_desktop_and_server_open_each_others_folders_without_migration(
    corpus_dir: Path, tmp_path: Path
) -> None:
    server = {
        **{k: v for k, v in os.environ.items() if not k.startswith("MOSAIC_DESKTOP")},
        "MOSAIC_MODE": "server",
        "MOSAIC_HOME": str(tmp_path / "server-home"),
        "MOSAIC_MEDIA_ROOTS": str(tmp_path / "media"),
    }
    media = tmp_path / "media"
    media.mkdir()
    # Desktop first: a trip made by the desktop app...
    a = _trip(corpus_dir, media)
    with backend(_env(tmp_path / "d1")) as b:
        made = b.ok("POST", "/api/projects", {"path": str(a)})
        assert b.wait(made["scan_job"]) == "done"
        pid_a = made["id"]
        clips_a = b.ok("GET", f"/api/projects/{pid_a}/inventory")["summary"]["clips"]
    rev_a = _schema(a)
    assert rev_a, "the project database was found and has a schema revision"
    # ...opens on a server (its own app data, a media root), as the same project.
    b_trip = _trip(corpus_dir, media, "Trip2")  # footage only: no project yet
    with _server(server) as srv:
        root = srv["roots"][0]["id"]
        opened = srv["call"]("POST", "/api/projects", {"root": root, "path": "Trip"})
        assert opened["id"] == pid_a, "recognised from its folder"
        assert srv["call"]("GET", f"/api/projects/{pid_a}/inventory")["summary"]["clips"] == clips_a
        # Server first: a trip made by the server...
        made = srv["call"]("POST", "/api/projects", {"root": root, "path": "Trip2"})
        pid_b = made["id"]
        _server_wait(srv, made["scan_job"])
        clips_b = srv["call"]("GET", f"/api/projects/{pid_b}/inventory")["summary"]["clips"]
    assert _schema(a) == rev_a, "no migration on the server"
    rev_b = _schema(b_trip)
    assert rev_b == rev_a
    # ...opens on a desktop that has never seen it (fresh app data).
    with backend(_env(tmp_path / "d2")) as b:
        made = b.ok("POST", "/api/projects", {"path": str(b_trip)})
        assert made["id"] == pid_b, "recognised from its folder"
        assert b.ok("GET", f"/api/projects/{pid_b}/inventory")["summary"]["clips"] == clips_b
    assert _schema(b_trip) == rev_b, "no migration on the desktop"


def _server_wait(srv: dict[str, Any], job: int, timeout: float = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if srv["call"]("GET", f"/api/jobs/{job}")["state"] == "done":
            return
        time.sleep(0.5)
    raise AssertionError(f"job {job} did not finish")


def _schema(trip: Path) -> str:
    """The schema revision of the trip's own project database (in its MosAic/ folder)."""
    import sqlite3

    revs: set[str] = set()
    for p in (trip / "MosAic").rglob("*.db"):
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            revs |= {r[0] for r in db.execute("SELECT version_num FROM alembic_version")}
        except sqlite3.Error:
            pass
        finally:
            db.close()
    return ",".join(sorted(revs))


@contextmanager
def _server(env: dict[str, str]) -> Iterator[dict[str, Any]]:
    proc = subprocess.Popen(
        [sys.executable, "-m", "mosaic.cli.main", "serve", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**env, "MOSAIC_BIND": "127.0.0.1", "MOSAIC_COOKIE_SECURE": "0"},
    )
    assert proc.stdout is not None
    port = None
    deadline = time.monotonic() + 120
    while port is None and time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line.startswith("MOSAIC_READY port="):
            port = int(line.split("=", 1)[1])
        elif not line:
            raise AssertionError("server exited")
    assert port, "no MOSAIC_READY from the server"
    base = f"http://127.0.0.1:{port}"
    cookies: dict[str, str] = {}

    def call(method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if data else {}
        if cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
            if method != "GET":
                h["X-CSRF-Token"] = cookies["mosaic_csrf"]
        req = urllib.request.Request(base + path, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=60) as r:
            for c in r.headers.get_all("Set-Cookie") or []:
                k, v = c.split(";", 1)[0].split("=", 1)
                cookies[k] = v
            raw = r.read()
        return json.loads(raw) if raw else None

    try:
        call("POST", "/api/auth/setup", {"password": "acceptance password"})
        yield {"call": call, "roots": call("GET", "/api/admin/media-roots")["items"]}
    finally:
        proc.terminate()
        proc.wait(timeout=60)
