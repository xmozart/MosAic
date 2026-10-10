"""`python -m mosaic.cli.main` runs the CLI: the Mac app starts the backend this way."""

from __future__ import annotations

import subprocess
import sys


def test_the_cli_runs_as_a_module() -> None:
    out = subprocess.run(
        [sys.executable, "-I", "-m", "mosaic.cli.main", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "serve" in out.stdout
