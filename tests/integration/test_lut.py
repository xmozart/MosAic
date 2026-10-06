"""LUTs end to end (M1 step 10b, ADR 0028): assigning a .cube LUT to a device changes its
proxies (darker, by a LUT that halves every channel) and their keys, and re-analysis
applies it; clearing it brings the original proxy back."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.storage.models_project import MediaFile
from tests.support.media import cell_mean, luma_frame
from tests.support.runner import run_job
from tests.unit.test_lut import cube

pytestmark = [pytest.mark.integration, pytest.mark.models]


def test_lut_changes_proxies(
    corpus_dir: Path, tmp_path: Path, ffmpeg_bin: FFmpegBinaries, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.media.proxy import load_proxy
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from tests.conftest import SHARED_MODELS

    if "MOSAIC_MODELS_DIR" not in os.environ:
        monkeypatch.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
    root = tmp_path / "trip"
    root.mkdir()
    shutil.copy(corpus_dir / "A001_basic.mp4", root / "A001_basic.mp4")
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "all", "fake", "fake")
    from mosaic.storage.projects import init_project

    project = init_project(control, me, root)
    executor = LocalExecutor(JobStore(control.db))
    assert run_job(control, submit_analysis(executor, me, project), timeout=900) == "done"

    def proxy_white() -> tuple[str, float]:
        with project.db.session() as s:
            aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == "A001_basic.mp4"))
        assert aid is not None
        px = load_proxy(project, aid)
        luma = luma_frame(ffmpeg_bin, px.path, px.width, px.height)
        return px.key, cell_mean(luma, 0, 0)  # the barcode's white sync cell

    key0, white0 = proxy_white()
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    url = f"/api/projects/{project.id}/devices"
    dev = client.get(url).json()["devices"][0]
    half = cube(tmp_path / "half.cube", 9, scale=0.5)
    r = client.put(url, json={"devices": [{"id": dev["id"], "lut_path": str(half)}]})
    assert r.status_code == 200, r.text
    assert r.json()["reanalysis_needed"]
    bad = tmp_path / "bad.cube"
    bad.write_text("nonsense")
    r2 = client.put(url, json={"devices": [{"id": dev["id"], "lut_path": str(bad)}]})
    assert r2.status_code == 422
    # Before re-analysis, previews keep working on the proxy without the LUT.
    assert proxy_white()[0] == key0
    assert client.put(url, json={"devices": [{"id": dev["id"]}]}).status_code == 422
    two = {"devices": [{"id": dev["id"], "clear_lut": True, "lut_path": str(half)}]}
    assert client.put(url, json=two).status_code == 422
    nobody = {"devices": [{"id": 999, "lut_path": str(half)}]}
    assert client.put(url, json=nobody).status_code == 404
    assert run_job(control, submit_analysis(executor, me, project), timeout=900) == "done"
    key1, white1 = proxy_white()
    assert key1 != key0
    assert white1 < white0 * 0.7, (white0, white1)
    half.unlink()  # the project keeps its own copy: renders stay reproducible
    r = client.put(url, json={"devices": [{"id": dev["id"], "clear_lut": True}]})
    assert r.status_code == 200
    assert run_job(control, submit_analysis(executor, me, project), timeout=900) == "done"
    key2, white2 = proxy_white()
    assert key2 == key0, "the original proxy (still in the store) is used again"
    assert abs(white2 - white0) < 2
    project.close()


def _proxy(ffmpeg_bin: FFmpegBinaries, src: Path, out: Path, lut: Path | None, full: bool) -> None:
    from fractions import Fraction

    from mosaic.media.ffmpeg import builders
    from mosaic.media.ffmpeg.run import run
    from mosaic.media.tools import working_h264_encoders

    spec = builders.ProxySpec(
        inputs=[src],
        video_index=0,
        audio_index=None,
        width=640,
        height=360,
        rate=Fraction(30000, 1001),
        hdr=None,
        full_range=full,
        encoder=working_h264_encoders()[0],
        bitrate="3M",
        out=out,
        lut=lut,
    )
    run(ffmpeg_bin, builders.proxy(spec))


@pytest.mark.parametrize(("name", "full"), [("A001_basic.mp4", False), ("full_range.mp4", True)])
def test_identity_lut_keeps_levels_through_odd_paths(
    corpus_dir: Path, tmp_path: Path, ffmpeg_bin: FFmpegBinaries, name: str, full: bool
) -> None:
    """An identity LUT in a folder named with an apostrophe, a colon, a comma and brackets
    renders, and leaves the levels of limited- and full-range sources as they were."""
    odd = tmp_path / "Mike's d:ir, [x]"
    odd.mkdir()
    ident = cube(odd / "id.cube", 17)
    plain, luted = tmp_path / "plain.mp4", tmp_path / "lut.mp4"
    _proxy(ffmpeg_bin, corpus_dir / name, plain, None, full)
    _proxy(ffmpeg_bin, corpus_dir / name, luted, ident, full)
    a = luma_frame(ffmpeg_bin, plain, 640, 360, 10)
    b = luma_frame(ffmpeg_bin, luted, 640, 360, 10)
    from mosaic.devtools import barcode

    for cell in ((0, 0), (0, barcode.COLS - 1)):  # the barcode's white and black cells
        assert abs(cell_mean(a, *cell) - cell_mean(b, *cell)) < 3, (name, cell)
    assert b.min() >= 12, "no sub-black levels"
