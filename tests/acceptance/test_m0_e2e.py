"""M0 acceptance 1, 4 and 5 on the synthetic corpus with the fake AI (docs/milestones/M0.md).

1. Every synthetic case goes analyze → edit → render; the corrupt file is unsupported with
   a reason; in the final render every event's barcodes match its EDL source range (±1).
4. No float time values in the DB's JSON rows or the edit JSON.
5. Re-running an identical edit makes zero AI calls.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import JSON, select

from mosaic.ai.adapters.fake import adapter as fake
from mosaic.core.timecheck import find_float_times
from mosaic.editing.generate import export_path
from mosaic.editing.request import EditRequest
from mosaic.editing.service import create_edit, get_version, submit_generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.pipeline import submit_analysis
from mosaic.render.service import create_render, get_render, submit_render
from mosaic.render.tasks import output_path
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import MediaFile, ProjectBase
from mosaic.storage.projects import Project, init_project
from tests.integration.test_render import _frames, _samples, _sources
from tests.support.runner import run_job

pytestmark = [pytest.mark.acceptance, pytest.mark.models]

REQUIRED = {
    "vfr": ["vfr.mp4"],
    "rotated": ["rotated_90.mp4", "rotated_270.mp4"],
    "hlg": ["hlg.mov"],
    "pq": ["pq.mov"],
    "start_offset": ["start_offset.mp4"],
    "chapters": ["GX010042.MP4"],
    "no_audio": ["no_audio.mp4"],
    "multi_audio": ["multi_audio.mov"],
    "hfr": ["hfr_120.mp4"],
    "full_range": ["full_range.mp4"],
    "hevc10": ["hevc10_5994.mov"],
}


@pytest.fixture(scope="module")
def e2e(corpus_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    # Module scope runs before the per-test home: give this module its own app data.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOSAIC_HOME", str(tmp_path_factory.mktemp("home-e2e")))
        root = tmp_path_factory.mktemp("e2e") / "trip"
        shutil.copytree(corpus_dir, root)
        control = ControlDB()
        me = control.local_principal
        ConfigService(control).set_provider(me, "all", "fake", "fake")
        project = init_project(control, me, root)
        executor = LocalExecutor(JobStore(control.db))
        assert run_job(control, submit_analysis(executor, me, project), timeout=1800) == "done"
        request = EditRequest(duration_s=150, chronology="strict", pace="energetic")
        edit_id = create_edit(project, request, control, me)
        first = len(fake.CALLS)
        job = submit_generate(executor, me, project, edit_id)
        assert run_job(control, job, timeout=600) == "done"
        assert len(fake.CALLS) > first, "the first edit must have called the planner/selector"
        yield project, control, edit_id, request
        project.close()


def _asset_of(project: Project, name: str) -> int | None:
    with project.db.session() as s:
        return s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == name))


def test_corrupt_file_is_listed_unsupported(e2e: Any) -> None:
    project = e2e[0]
    with project.db.session() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == "corrupt.mp4"))
    assert mf is not None
    assert mf.status == "unsupported"
    assert mf.reason


def test_every_case_is_edited_and_renders_frame_exact(e2e: Any, ffmpeg_bin: FFmpegBinaries) -> None:
    project, control, edit_id, _ = e2e
    v = get_version(project, edit_id)
    assert v.metrics["blocking_ok"], (v.metrics, v.findings)
    events = v.timeline["tracks"][0]["events"]
    used = {int(e["asset_id"][4:]) for e in events}
    missing = []
    for case, files in REQUIRED.items():
        for f in files:
            aid = _asset_of(project, f)
            if aid is None or aid not in used:
                missing.append(f"{case}:{f}")
    assert not missing, f"cases not in the edit: {missing}; {v.metrics['retrieval']}"

    rid = create_render(project, edit_id, v.version, "final", lossless=True)
    job = submit_render(LocalExecutor(JobStore(control.db)), control.local_principal, project, rid)
    assert run_job(control, job, timeout=1800) == "done"
    r = get_render(project, rid)
    assert r is not None
    path = output_path(project.workspace, r)
    from fractions import Fraction

    from mosaic.core.time import parse_rational
    from mosaic.devtools.render_check import check_render
    from mosaic.render.plan import samples_for

    total = v.timeline["duration"]["frames"]
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, parse_rational(v.rate))
    checks = check_render(ffmpeg_bin, path, v.timeline, _sources(project, ffmpeg_bin, used))
    bad = [(c.event_id, c.asset_id, c.decoded, c.frames, c.errors) for c in checks if not c.ok]
    assert not bad, bad
    assert Fraction(total) / parse_rational(v.rate) > 100


def test_no_float_times_in_db_or_edit_json(e2e: Any) -> None:
    project, _, edit_id, _ = e2e
    found: list[str] = []
    with project.db.session() as s:
        for table in ProjectBase.metadata.sorted_tables:
            cols = [c for c in table.columns if isinstance(c.type, JSON)]
            if not cols:
                continue
            for row in s.execute(select(*cols)):
                for col, value in zip(cols, row, strict=True):
                    found += find_float_times(value, f"{table.name}.{col.name}")
    v = get_version(project, edit_id)
    found += find_float_times(
        json.loads(export_path(project.workspace, edit_id, v.version).read_text())
    )
    assert found == []


def test_identical_edit_makes_zero_ai_calls(e2e: Any) -> None:
    project, control, edit_id, request = e2e
    before = len(fake.CALLS)
    again = create_edit(project, request, control, control.local_principal)
    assert again == edit_id
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    assert len(fake.CALLS) == before
