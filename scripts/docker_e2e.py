"""M2 acceptance 1 against a real container (ADR 0056): from `docker compose up` with one
media root to a first rendered preview, through the HTTP API the web UI calls. No CLI.

Run by `scripts/docker-e2e.sh`, which starts and removes the compose project. Uses only the
standard library; cookies are carried by hand because the session cookie is `Secure` and
this talks plain HTTP to localhost, as a browser may.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from typing import Any

BASE = sys.argv[1].rstrip("/")
PASSWORD = "docker e2e password"
cookies: dict[str, str] = {}


def call(
    method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
) -> tuple[int, Any, bytes]:
    data = None if body is None else json.dumps(body).encode()
    h = {"Content-Type": "application/json"} if data else {}
    h.update(headers or {})
    if cookies:
        h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    if "mosaic_csrf" in cookies and method != "GET":
        h["X-CSRF-Token"] = cookies["mosaic_csrf"]
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw, hdrs = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), e.headers
    for line in hdrs.get_all("Set-Cookie") or []:
        for k, m in SimpleCookie(line).items():
            cookies[k] = m.value
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None
    return status, parsed, raw


def ok(
    method: str, path: str, body: Any = None, want: tuple[int, ...] = (200, 201, 202, 204)
) -> Any:
    status, parsed, raw = call(method, path, body)
    if status not in want:
        sys.exit(f"{method} {path} → {status}: {raw[:400]!r}")
    return parsed


def wait(job: int, what: str, timeout: float) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        j = ok("GET", f"/api/jobs/{job}")
        if j["state"] == "done":
            print(f"  {what}: done in {time.monotonic() - t0:.0f} s")
            return
        if j["state"] in ("failed", "cancelled"):
            sys.exit(f"{what} {j['state']}: {j.get('error')}")
        time.sleep(2)
    sys.exit(f"{what}: timed out")


def main() -> None:
    assert ok("GET", "/api/auth/status")["setup_required"] is True
    ok("POST", "/api/auth/setup", {"password": PASSWORD})
    ok("PATCH", "/api/providers", {"all": {"provider": "fake", "model": "fake"}})
    roots = ok("GET", "/api/admin/media-roots")["items"]
    root = (
        roots[0]["id"] if roots else ok("POST", "/api/admin/media-roots", {"path": "/media"})["id"]
    )
    pv = ok("POST", "/api/projects/preview", {"root": root, "path": "Trip"})
    print(f"  preview: placement {pv['placement']}, fs {pv['fs_class']}")
    made = ok("POST", "/api/projects", {"root": root, "path": "Trip"})
    pid = made["id"]
    wait(made["scan_job"], "scan", 600)
    run = ok("POST", f"/api/projects/{pid}/analysis-runs", {"mode": "quick", "cost_limit": 1.0})
    wait(run["job_id"], "analysis (quick; first run downloads models)", 3600)
    request = {"duration_s": 20, "story": "cinematic_journey", "aspect": "16:9"}
    created = ok("POST", f"/api/projects/{pid}/edits", {"request": request})
    wait(created["job_id"], "edit", 1200)
    r = ok("POST", "/api/renders", {"edit_id": created["edit_id"], "final": False})
    wait(r["job_id"], "preview render", 1200)
    status, _, body = call(
        "GET",
        f"/api/projects/{pid}/renders/{r['render_id']}/file",
        headers={"Range": "bytes=0-1023"},
    )
    if status != 206 or len(body) != 1024:
        sys.exit(f"ranged playback: {status}, {len(body)} bytes")
    print("docker e2e: ok (first rendered preview reached from the API)")


if __name__ == "__main__":
    main()
