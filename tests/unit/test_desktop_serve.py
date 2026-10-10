"""`mosaic serve --port 0 --token-stdin`, as the desktop shell starts it (ADR 0057): it
announces its port, enforces the token over real HTTP, and keeps the token out of its
environment."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

TOKEN = "shell-token-for-the-serve-test-0123456789"
SERVE = [sys.executable, "-c", "from mosaic.cli.main import cli; cli()", "serve", "--port", "0"]


def _status(url: str, token: str | None = None) -> int:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return e.code


def _ready(proc: subprocess.Popen[str], timeout: float = 60) -> int:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        if line.startswith("MOSAIC_READY port="):
            return int(line.strip().split("=", 1)[1])
    raise AssertionError(f"no MOSAIC_READY line (exit {proc.poll()})")


def test_serve_announces_its_port_and_enforces_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAIC_MODE", "desktop")
    monkeypatch.delenv("MOSAIC_DESKTOP_TOKEN", raising=False)
    proc = subprocess.Popen(
        [*SERVE, "--token-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(TOKEN + "\n")
        proc.stdin.close()
        port = _ready(proc)
        base = f"http://127.0.0.1:{port}"
        assert _status(f"{base}/api/health") == 200
        assert _status(f"{base}/api/jobs") == 401
        assert _status(f"{base}/api/jobs", "wrong-token") == 401
        assert _status(f"{base}/api/jobs", TOKEN) == 200
        # Not in the process's environment, where same-user tools could read it.
        env = subprocess.run(
            ["ps", "eww", "-p", str(proc.pid)], capture_output=True, text=True, check=False
        ).stdout
        assert TOKEN not in env
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def test_serve_refuses_to_start_with_an_empty_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAIC_MODE", "desktop")
    monkeypatch.setenv("MOSAIC_DESKTOP_TOKEN", "")
    proc = subprocess.run(SERVE, capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode != 0
    assert "MOSAIC_READY" not in proc.stdout
    assert "desktop token" in proc.stderr
