"""Regenerate the Python package tables in LICENSES.md from uv.lock + installed metadata.

Usage: uv run python scripts/update_licenses.py
Hand-written sections outside the BEGIN/END markers are preserved.
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Platform-specific packages not installed on macOS (licenses checked on PyPI).
KNOWN = {
    "colorama": "BSD-3-Clause",
    "httpx2-jsfetch": "BSD-3-Clause",
    "av": "NOT INSTALLED: excluded by override, its wheels bundle GPL FFmpeg (ADR 0009)",
    # keyring's Linux/Windows backends (licenses checked on PyPI)
    "cffi": "MIT-0",
    "cryptography": "Apache-2.0 OR BSD-3-Clause",
    "jeepney": "MIT",
    "pycparser": "BSD-3-Clause",
    "pywin32-ctypes": "BSD-3-Clause",
    "secretstorage": "BSD-3-Clause",
}
BEGIN, END = "<!-- BEGIN python-packages -->", "<!-- END python-packages -->"


def _license(name: str) -> str:
    try:
        meta = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return KNOWN.get(name, "(platform-specific; not installed here)")
    expr = meta.get("License-Expression")
    if expr:
        return expr
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    text = (meta.get("License") or "").strip().splitlines()
    return text[0][:60] if text else "UNKNOWN"


def _closure(lock: dict, roots: list[str]) -> set[str]:
    by_name = {p["name"]: p for p in lock["package"]}
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n in seen or n not in by_name:
            continue
        seen.add(n)
        stack += [d["name"] for d in by_name[n].get("dependencies", [])]
    return seen


def main() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    by_name = {p["name"]: p for p in lock["package"]}
    root = by_name["mosaic"]
    runtime = _closure(lock, [d["name"] for d in root.get("dependencies", [])])
    dev_roots = [d["name"] for grp in root.get("dev-dependencies", {}).values() for d in grp]
    dev = _closure(lock, dev_roots) - runtime
    other = set(by_name) - runtime - dev - {"mosaic"}

    def table(names: set[str]) -> str:
        rows = ["| Package | Version | License |", "|---|---|---|"]
        for n in sorted(names):
            rows.append(f"| {n} | {by_name[n].get('version', '')} | {_license(n)} |")
        return "\n".join(rows)

    body = (
        f"{BEGIN}\n\n### Runtime (Python)\n\nUsed as imported libraries by the backend.\n\n"
        f"{table(runtime | other)}\n\n### Development only (Python)\n\nTests, lint and type "
        f"checks; never shipped.\n\n{table(dev)}\n\n{END}"
    )
    path = ROOT / "LICENSES.md"
    text = path.read_text()
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), body, text, flags=re.S)
    path.write_text(text)


if __name__ == "__main__":
    main()
