"""The server image's files, checked without Docker (ADR 0055): what `make docker` and the
step 11 compose run test live, CI guards statically."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_passes_the_master_key_as_a_secret_and_reaps_workers() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    svc = compose["services"]["mosaic"]
    env = svc["environment"]
    assert "MOSAIC_MASTER_KEY" not in env, "never the key itself in the environment"
    assert env["MOSAIC_MASTER_KEY_FILE"] == "/run/secrets/mosaic_master_key"
    assert "mosaic_master_key" in svc["secrets"]
    assert "mosaic_master_key" in compose["secrets"]
    assert svc["init"] is True
    assert any(v.endswith(":/data") for v in svc["volumes"])
    nvidia = yaml.safe_load((ROOT / "compose.nvidia.yaml").read_text())
    assert (
        nvidia["services"]["mosaic"]["deploy"]["resources"]["reservations"]["devices"][0]["driver"]
        == "nvidia"
    )


def test_the_image_is_lgpl_non_root_pinned_and_keeps_live_dbs_in_data() -> None:
    df = (ROOT / "Dockerfile").read_text()
    assert "--enable-gpl" in df, "the GPL refusal"
    assert "sha256sum -c" in df
    assert re.search(r"FFMPEG_SHA256_AMD64=[0-9a-f]{64}", df)
    assert re.search(r"FFMPEG_SHA256_ARM64=[0-9a-f]{64}", df)
    assert re.search(r"astral-sh/uv:\d+\.\d+\.\d+ ", df), "an exact uv version"
    assert "MOSAIC_FOLDER_DB=never" in df
    assert re.search(r"^USER mosaic$", df, re.M)
    assert "HEALTHCHECK" in df
    assert "/api/health" in df
    assert "--frozen --no-dev" in df
    assert "x264" not in df.replace("no libx264", "")
