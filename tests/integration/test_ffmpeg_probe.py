from __future__ import annotations

import pytest

from mosaic.media.ffmpeg.capabilities import (
    FFmpegBinaries,
    FFmpegLicense,
    ensure_license_allowed,
    probe_capabilities,
)

pytestmark = pytest.mark.integration


def test_dev_and_ci_ffmpeg_is_lgpl(ffmpeg_bin: FFmpegBinaries) -> None:
    caps = probe_capabilities(ffmpeg_bin.ffmpeg)
    assert caps.license is FFmpegLicense.LGPL, caps.configuration
    ensure_license_allowed(caps)
    assert caps.can_tonemap
    assert caps.h264_encoders(), "an H.264 encoder (VideoToolbox/NVENC/openh264) is required"
    assert caps.has_encoder("ffv1")
