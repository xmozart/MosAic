"""M0 acceptance 6: LICENSES.md lists every dependency, model and fixture; FFmpeg is LGPL."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.media.ffmpeg.capabilities import FFmpegBinaries, FFmpegLicense, probe_capabilities

pytestmark = pytest.mark.acceptance
ROOT = Path(__file__).resolve().parents[2]


def test_ffmpeg_probe_reports_lgpl(ffmpeg_bin: FFmpegBinaries) -> None:
    assert probe_capabilities(ffmpeg_bin.ffmpeg).license is FFmpegLicense.LGPL


def test_every_committed_fixture_is_listed() -> None:
    listed = (ROOT / "LICENSES.md").read_text()
    fixtures = [
        p
        for p in (ROOT / "tests" / "fixtures").rglob("*")
        if p.is_file() and not p.name.startswith(".")
    ]
    missing = [str(p.relative_to(ROOT)) for p in fixtures if str(p.relative_to(ROOT)) not in listed]
    assert not missing, f"add to LICENSES.md test fixtures: {missing}"


def test_locked_python_packages_are_listed() -> None:
    from tests.unit.test_licenses import test_every_locked_package_is_listed

    test_every_locked_package_is_listed()
