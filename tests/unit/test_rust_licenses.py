"""The desktop shell's crate-licence check (ADR 0060) reads SPDX expressions correctly."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_rust_licenses",
    Path(__file__).resolve().parents[2] / "scripts" / "check_rust_licenses.py",
)
assert spec is not None
assert spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.mark.parametrize(
    ("expr", "ok"),
    [
        ("MIT", True),
        ("MIT OR Apache-2.0", True),
        ("MIT/Apache-2.0", True),
        ("MIT OR Apache-2.0 OR LGPL-2.1-or-later", True),
        ("Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT", True),
        ("(MIT OR Apache-2.0) AND Unicode-3.0", True),
        ("GPL-3.0", False),
        ("(MIT OR GPL-3.0) AND GPL-3.0", False),
        ("MIT AND GPL-2.0", False),
        ("", False),
        ("(MIT", False),
    ],
)
def test_spdx_expressions(expr: str, ok: bool) -> None:
    assert mod.acceptable(expr) is ok
