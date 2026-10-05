"""Rendering on the analyzed synthetic corpus (M0 step 11)."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.core.time import parse_rational
from mosaic.devtools.render_check import SourceInfo, check_render
from mosaic.editing.request import EditRequest
from mosaic.editing.service import create_edit, get_version, submit_generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.ffmpeg.builders import ffprobe_video_pts
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run
from mosaic.render.plan import samples_for
from mosaic.render.service import create_render, get_render, submit_render
from mosaic.render.tasks import output_path
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Artifact, Asset, AssetFile, MediaFile, MediaStream
from mosaic.storage.projects import Project
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def edit(analyzed_session: Any) -> tuple[Project, ControlDB, int, int]:
    project, control = analyzed_session
    edit_id = create_edit(
        project, EditRequest(duration_s=45, chronology="strict"), control, control.local_principal
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    return project, control, edit_id, get_version(project, edit_id).version


def _render(
    project: Project, control: ControlDB, edit_id: int, version: int, kind: str, lossless: bool
) -> int:
    rid = create_render(project, edit_id, version, kind, lossless)
    job = submit_render(LocalExecutor(JobStore(control.db)), control.local_principal, project, rid)
    assert run_job(control, job, timeout=900) == "done"
    return rid


def _sources(project: Project, binaries: FFmpegBinaries, assets: set[int]) -> dict[str, SourceInfo]:
    out = {}
    with project.db.session() as s:
        for aid in assets:
            a = s.get(Asset, aid)
            assert a is not None
            assert a.tb is not None
            pts = None
            if a.vfr:
                rows = list(
                    s.execute(
                        select(MediaFile.rel_path, MediaStream.time_base, MediaStream.start_pts)
                        .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
                        .join(MediaStream, MediaStream.media_file_id == MediaFile.id)
                        .where(
                            AssetFile.asset_id == aid,
                            MediaStream.stream_index == a.video_stream_index,
                        )
                    )
                )
                rel, tb, start = rows[0]
                res = run(
                    binaries, ffprobe_video_pts(project.root / rel, a.video_stream_index or 0)
                )
                ticks = sorted(
                    int(x) for x in res.stdout.decode().split() if x.strip().lstrip("-").isdigit()
                )
                pts = [Fraction(t - start) * parse_rational(tb) for t in ticks]
            out[f"ast_{aid:04d}"] = SourceInfo(
                rate=None if a.vfr else parse_rational(a.rate or "30"),
                pts=pts,
                offset=0,
                display=(a.display_width or 640, a.display_height or 360),
            )
    return out


def _samples(binaries: FFmpegBinaries, path: Any) -> int:
    raw = subprocess.run(
        [
            str(binaries.ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a",
            "-f",
            "s16le",
            "-ac",
            "2",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return len(raw) // 4


def _frames(binaries: FFmpegBinaries, path: Any) -> int:
    out = subprocess.run(
        [
            str(binaries.ffprobe),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def test_final_render_is_frame_exact(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    rid = _render(project, control, edit_id, version, "final", lossless=True)
    r = get_render(project, rid)
    assert r is not None
    assert r.status == "done"
    path = output_path(project.workspace, r)
    total = v.timeline["duration"]["frames"]
    rate = parse_rational(v.rate)
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, rate)
    assert r.metrics["true_peak_dbtp"] is not None  # the corpus edit has audio
    assert r.metrics["true_peak_dbtp"] <= -1.0
    if r.metrics["normalized"]:
        assert abs(r.metrics["loudness_lufs"] - (-14.0)) <= 1.0
    events = v.timeline["tracks"][0]["events"]
    assets = {int(e["asset_id"][4:]) for e in events}
    checks = check_render(ffmpeg_bin, path, v.timeline, _sources(project, ffmpeg_bin, assets))
    bad = [(c.event_id, c.asset_id, c.decoded, c.frames, c.errors) for c in checks if not c.ok]
    assert not bad, bad


def test_preview_and_chunk_reuse(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    rid = _render(project, control, edit_id, version, "preview", lossless=False)
    r = get_render(project, rid)
    assert r is not None
    path = output_path(project.workspace, r)
    assert path.suffix == ".mp4"
    assert _frames(ffmpeg_bin, path) == v.timeline["duration"]["frames"]
    # Constant frame rate on the exact timeline grid; true peak within the limit after AAC.
    from mosaic.media.ffmpeg.builders import ffprobe_stream_counts

    streams = json.loads(run(ffmpeg_bin, ffprobe_stream_counts(path)).stdout)["streams"]
    video = next(st for st in streams if st["codec_type"] == "video")
    assert parse_rational(video["avg_frame_rate"]) == parse_rational(v.rate)
    assert r.metrics["true_peak_dbtp"] is not None
    assert r.metrics["true_peak_dbtp"] <= -1.0
    with project.db.session() as s:
        before = s.query(Artifact).filter(Artifact.kind == "chunk").count()
    _render(project, control, edit_id, version, "preview", lossless=False)
    with project.db.session() as s:
        after = s.query(Artifact).filter(Artifact.kind == "chunk").count()
    assert after == before, "an unchanged event's chunk is reused"


def test_render_api(edit: tuple[Project, ControlDB, int, int]) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.models_project import Edit

    project, control, edit_id, _ = edit
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    with project.db.session() as s:
        e = s.get(Edit, edit_id)
        assert e is not None
        uid = e.uid
    started = client.post(f"/api/edits/{uid}/preview")
    assert started.status_code == 202
    assert run_job(control, started.json()["job_id"], timeout=900) == "done"
    items = client.get(f"/api/projects/{project.id}/renders").json()["items"]
    mine = next(i for i in items if i["render_id"] == started.json()["render_id"])
    assert mine["status"] == "done"
    assert "-preview-r" in mine["path"]
    assert mine["path"].endswith(".mp4")
    assert client.post("/api/renders", json={"edit_id": uid, "version": "x"}).status_code == 422
    assert client.post("/api/renders", json={"edit_id": "nope"}).status_code == 404
