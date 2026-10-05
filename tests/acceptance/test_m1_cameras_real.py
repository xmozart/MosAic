"""M1 acceptance 4 on real footage (read-only; MEDIA_SUPPORT.md §2, ADR 0024).

The owner's corpus (``Samples/`` locally, not in git; ``MOSAIC_REAL_FIXTURES`` overrides)
holds GoPro and iPhone recordings. Each is probed in place, never written, and classified
by the camera profiles. Cameras without real footage yet (Insta360, DJI, Nikon video) are
covered by synthetic stand-ins (tests/integration/test_cameras.py) until the owner adds
samples (docs/OPEN_QUESTIONS.md Q-3).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mosaic.media import probe as probing
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.profiles import FileRecord, profile_for
from mosaic.media.scan import MediaType

pytestmark = [pytest.mark.acceptance]

REAL = Path(os.environ.get("MOSAIC_REAL_FIXTURES", Path(__file__).parents[2] / "Samples"))


def _classify(ffmpeg_bin: FFmpegBinaries, path: Path) -> tuple[str, str]:
    before = path.stat()
    result = probing.parse_probe(probing.ffprobe(ffmpeg_bin, path))
    after = path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns), (
        "originals are read-only (invariant 1)"
    )
    rec = FileRecord(0, path.name, MediaType.VIDEO, result, usable=True)
    profile = profile_for(rec)
    return profile.id, profile.capability(result, path.name).level


def _videos(trip: str, pattern: str) -> list[Path]:
    folder = REAL / trip
    return sorted(p for p in folder.glob(pattern) if p.is_file()) if folder.is_dir() else []


@pytest.mark.skipif(not _videos("Airshow", "GX*.MP4"), reason="no real GoPro footage here")
def test_real_gopro(ffmpeg_bin: FFmpegBinaries) -> None:
    for path in _videos("Airshow", "GX*.MP4")[:3]:
        assert _classify(ffmpeg_bin, path) == ("gopro", "full"), path.name


@pytest.mark.skipif(not _videos("Dubai", "*_iOS.MOV"), reason="no real iPhone footage here")
def test_real_iphone(ffmpeg_bin: FFmpegBinaries) -> None:
    for path in _videos("Dubai", "*_iOS.MOV"):
        assert _classify(ffmpeg_bin, path) == ("iphone", "full"), path.name
