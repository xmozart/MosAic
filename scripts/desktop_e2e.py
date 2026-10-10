"""The bundled backend, run as the Mac app runs it, from a folder to a rendered preview
(M3 acceptance 1; ADR 0061). Run by scripts/check-desktop-bundle.sh with the bundle's own
Python and an empty environment: standard library and the bundled mosaic only.

    python3 scripts/desktop_e2e.py <MosAic.app/Contents/Resources>
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RES = Path(sys.argv[1])
TOKEN = secrets.token_hex(32)
CLIPS = ("A001_basic.mp4", "A002_basic.mp4", "no_audio.mp4")  # needs no test fixture


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="mosaic-desktop-e2e-"))
    env = {
        "HOME": os.environ["HOME"],
        "PATH": "/usr/bin:/bin",
        "TMPDIR": tempfile.gettempdir(),
        "MOSAIC_MODE": "desktop",
        "MOSAIC_HOME": str(work / "home"),
        "MOSAIC_UI_DIR": str(RES / "ui"),
        "MOSAIC_FFMPEG_DIR": str(RES / "ffmpeg"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",  # no Keychain prompts
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.environ.get("MOSAIC_MODELS_DIR"):
        env["MOSAIC_MODELS_DIR"] = os.environ["MOSAIC_MODELS_DIR"]
    os.environ.update(env)
    try:
        trip = work / "Trip"
        trip.mkdir()
        from mosaic.devtools.corpus import CorpusGenerator
        from mosaic.media.ffmpeg.capabilities import locate

        ffmpeg = locate()
        assert str(ffmpeg.ffmpeg).startswith(str(RES)), f"not the bundled FFmpeg: {ffmpeg.ffmpeg}"
        corpus = work / "corpus"
        CorpusGenerator(corpus, ffmpeg).generate()
        for name in CLIPS:
            shutil.copy2(corpus / name, trip / name)
        run(trip, env)
        print("desktop e2e: ok (bundled backend, folder to rendered preview)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def embeddings(trip: Path, home: Path) -> int:
    """Image embeddings in the trip's project database (wherever placement put it)."""
    import sqlite3

    total = 0
    for db_path in [*trip.rglob("*.db"), *home.rglob("*.db")]:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)  # read only: the backend owns it
        try:
            total += db.execute("SELECT count(*) FROM embedding").fetchone()[0]
        except sqlite3.Error:
            pass
        finally:
            db.close()
    return int(total)


def run(trip: Path, env: dict[str, str]) -> None:
    proc = subprocess.Popen(
        [
            str(RES / "backend" / "bin" / "python3"),
            "-I",  # as the shell runs it: isolated, and no bytecode written into the app
            "-B",
            "-m",
            "mosaic.cli.main",
            "serve",
            "--port",
            "0",
            "--token-stdin",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(TOKEN + "\n")
    proc.stdin.flush()
    try:
        port = None
        deadline = time.monotonic() + 120
        while port is None and time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line.startswith("MOSAIC_READY port="):
                port = int(line.split("=", 1)[1])
            elif not line and proc.poll() is not None:
                raise SystemExit(f"the backend exited ({proc.returncode})")
        assert port, "no MOSAIC_READY"
        base = f"http://127.0.0.1:{port}"

        def call(
            method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
        ) -> tuple[int, bytes]:
            data = None if body is None else json.dumps(body).encode()
            h = {
                "Authorization": f"Bearer {TOKEN}",
                **({"Content-Type": "application/json"} if data else {}),
                **(headers or {}),
            }
            req = urllib.request.Request(base + path, data=data, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()

        def ok(method: str, path: str, body: Any = None) -> Any:
            status, raw = call(method, path, body)
            if status >= 300:
                raise SystemExit(f"{method} {path} -> {status}: {raw[:300]!r}")
            return json.loads(raw) if raw else None

        def wait(job: int, what: str, timeout: float) -> None:
            t0 = time.monotonic()
            while time.monotonic() - t0 < timeout:
                state = ok("GET", f"/api/jobs/{job}")["state"]
                if state == "done":
                    print(f"  {what}: {time.monotonic() - t0:.0f} s")
                    return
                if state in ("failed", "cancelled"):
                    raise SystemExit(f"{what}: {state}")
                time.sleep(1)
            raise SystemExit(f"{what}: timed out")

        assert call("GET", "/api/jobs", headers={"Authorization": ""})[0] == 401, (
            "the token is required"
        )
        # Cloud tasks on the offline fake; image understanding on the real local SigLIP
        # (ONNX Runtime inside the app), so the bundle's native code really runs.
        ok("PATCH", "/api/providers", {"all": {"provider": "fake", "model": "fake"}})
        ok(
            "PATCH",
            "/api/providers",
            {"embedder": {"provider": "siglip-onnx", "model": "quantized"}},
        )
        made = ok("POST", "/api/projects", {"path": str(trip)})
        wait(made["scan_job"], "scan", 600)
        run_ = ok(
            "POST",
            f"/api/projects/{made['id']}/analysis-runs",
            {"mode": "quick", "cost_limit": 1.0},
        )
        wait(run_["job_id"], "analysis (quick)", 3600)
        n = embeddings(trip, Path(env["MOSAIC_HOME"]))
        assert n > 0, "SigLIP (ONNX Runtime in the app) produced no embeddings"
        print(f"  embeddings: {n}")
        edit = ok("POST", f"/api/projects/{made['id']}/edits", {"request": {"duration_s": 15}})
        wait(edit["job_id"], "edit", 1200)
        render = ok("POST", "/api/renders", {"edit_id": edit["edit_id"], "final": False})
        wait(render["job_id"], "preview render", 1200)
        status, body = call(
            "GET",
            f"/api/projects/{made['id']}/renders/{render['render_id']}/file",
            headers={"Range": "bytes=0-1023"},
        )
        assert status == 206, status
        assert len(body) == 1024, len(body)
    finally:
        proc.stdin.close()  # the lifeline: the backend stops
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
