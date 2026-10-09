"""M1 acceptance 6 (docs/milestones/M1.md; ADR 0031): the 40-hour synthetic project
completes L0/L1 with bounded memory, and a library list page answers in under 300 ms.

The project (400 six-minute clips over five days) is generated once into
``.cache/long-40h`` and reused; each run analyzes a linked copy. The worker runs as its
own process, which reports its peak resident memory when it exits.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from mosaic.core.modes import resolve
from mosaic.devtools.longproject import MANIFEST, LongSpec, generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.pipeline import submit_analysis
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, SampleFrame, Segment
from mosaic.storage.projects import init_project

pytestmark = pytest.mark.acceptance

REPO = Path(__file__).resolve().parents[2]
LONG_DIR = Path(os.environ.get("MOSAIC_LONG_PROJECT_DIR", REPO / ".cache" / "long-40h"))
SPEC = LongSpec()
PEAK_RSS_BYTES = 1536 * 1024 * 1024  # the worker process, whole L0/L1 run
LIST_PAGE_S = 0.300
# S14 asks for an estimate after each pause in typing (400 ms debounce); it runs the edit's
# retrieval in the request (ADR 0047). M2 step 11 budget on this fixture.
ESTIMATE_S = 2.0

# Runs the worker in this process and prints its peak RSS (bytes) as the last line.
WORKER = """
import resource, sys
from mosaic.jobs.worker import main
main(["--exit-when-idle", "5"])
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(peak if sys.platform == "darwin" else peak * 1024)  # Linux reports KiB
"""


def _link_copy(src: Path, dst: Path) -> None:
    """The clips as hard links (fast, no extra space); analysis never writes them."""
    dst.mkdir()
    for f in sorted(src.iterdir()):
        if f.name == MANIFEST or not f.is_file():
            continue
        try:
            os.link(f, dst / f.name)
        except OSError:
            shutil.copy2(f, dst / f.name)


@pytest.mark.timeout(3600)
def test_forty_hours_l0_l1_bounded_memory_and_fast_list(
    tmp_path: Path, ffmpeg_bin: FFmpegBinaries
) -> None:
    generate(LONG_DIR, ffmpeg_bin, SPEC)
    root = tmp_path / "long-trip"
    _link_copy(LONG_DIR, root)

    control = ControlDB()
    me = control.local_principal
    config = ConfigService(control)
    config.set_provider(me, "all", "fake", "fake")
    config.set_provider(me, "embedder", "fake", "fake")  # SigLIP speed is not under test
    project = init_project(control, me, root)
    pid = project.id
    job = submit_analysis(
        LocalExecutor(JobStore(control.db)), me, project, resolve("custom", {"l2": False})
    )
    project.close()

    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", WORKER], capture_output=True, text=True, timeout=3300
    )
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, proc.stderr[-3000:]
    peak = int(proc.stdout.strip().splitlines()[-1])

    store = JobStore(control.db)
    status = store.job(job)
    assert status is not None
    failed = [(t.kind, (t.error or "")[:200]) for t in store.tasks(job) if t.status == "failed"]
    assert status.status == "done", failed

    from mosaic.storage.projects import open_project

    p = open_project(control, me, root, read_only=True)
    with p.db.session() as s:
        assets = s.scalar(select(func.count(Asset.id)).where(Asset.status == "ok"))
        segments = s.scalar(select(func.count(Segment.id))) or 0
        samples = s.scalar(select(func.count(SampleFrame.id))) or 0
    p.close()
    assert assets == SPEC.clips
    assert segments > 5_000
    assert samples > 20_000

    times = _list_pages(control, pid)
    estimates = _estimates(control, pid)
    report = {
        "hours": SPEC.hours,
        "clips": SPEC.clips,
        "segments": segments,
        "samples": samples,
        "l0_l1_seconds": round(elapsed),
        "worker_peak_rss_mb": round(peak / 2**20),
        "list_pages": len(times),
        "list_page_ms_max": round(max(times) * 1000, 1),
        "estimate_ms_max": round(max(estimates) * 1000, 1),
    }
    print("SCALE", json.dumps(report))
    report_file = REPO / ".cache" / "scale-report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2))
    assert peak < PEAK_RSS_BYTES, report
    assert max(times) < LIST_PAGE_S, report
    assert max(estimates) < ESTIMATE_S, report


def _list_pages(control: ControlDB, pid: str) -> list[float]:
    """Walk every library page (day and camera grouping); the time of each response
    after the first request, which opens the project."""
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    url = f"/api/projects/{pid}/library"
    assert client.get(url, params={"limit": 1}).status_code == 200  # warm-up
    times: list[float] = []
    seen: dict[str, int] = {}
    for group in ("day", "camera"):
        cursor: str | None = None
        n = 0
        while True:
            params: dict[str, Any] = {"group": group, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            t = time.perf_counter()
            r = client.get(url, params=params)
            times.append(time.perf_counter() - t)
            assert r.status_code == 200, r.text
            body = r.json()
            n += len(body["items"])
            cursor = body["next_cursor"]
            if not cursor:
                break
        seen[group] = n
    assert seen == {"day": SPEC.clips, "camera": SPEC.clips}
    return times


def _estimates(control: ControlDB, pid: str) -> list[float]:
    """S14's estimate for a few requests on the 40-hour project (M2; STATUS)."""
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    times: list[float] = []
    for request in (
        {"duration_s": 60},
        {"duration_s": 300, "story": "cinematic_journey"},
        {"duration_s": 600, "story": "chronological_diary", "chronology": "strict"},
    ):
        t = time.perf_counter()
        r = client.post("/api/edits/estimate", json={"project_id": pid, "request": request})
        times.append(time.perf_counter() - t)
        assert r.status_code == 200, r.text
    return times
