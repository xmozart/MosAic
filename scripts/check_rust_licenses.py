"""Fails on a Rust crate in the desktop shell whose license is outside CLAUDE.md's allowed
list (ADR 0060). Run by `make desktop-check`; needs cargo."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# CLAUDE.md "Dependency licensing", plus Unicode-3.0 (ICU data crates; ADR 0060).
ALLOWED = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MPL-2.0",
    "Zlib",
    "Unlicense",
    "CC0-1.0",
    "0BSD",
    "BSL-1.0",
    "Unicode-3.0",
    "Unicode-DFS-2016",
    "Apache-2.0 WITH LLVM-exception",
}
OWN = {"mosaic-desktop"}


def acceptable(expr: str) -> bool:
    """Evaluates an SPDX expression: an id is allowed if listed; ``A AND B`` needs both,
    ``A OR B`` either (AND binds tighter); brackets group. ``/`` is the old OR."""
    tokens = re.findall(r"\(|\)|[^\s()]+", expr.replace("/", " OR "))
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def atom() -> bool:
        tok = take()
        if tok == "(":
            ok = either()
            if take() != ")":
                raise ValueError(expr)
            return ok
        if peek() == "WITH":  # e.g. Apache-2.0 WITH LLVM-exception
            take()
            return f"{tok} WITH {take()}" in ALLOWED
        return tok in ALLOWED

    def both() -> bool:
        ok = atom()
        while peek() == "AND":
            take()
            ok = atom() and ok
        return ok

    def either() -> bool:
        ok = both()
        while peek() == "OR":
            take()
            ok = both() or ok
        return ok

    if not tokens:
        return False
    try:
        result = either()
    except (IndexError, ValueError):
        return False
    return result and pos == len(tokens)


def main() -> int:
    meta = json.loads(
        subprocess.run(
            ["cargo", "metadata", "--format-version", "1", "--locked"],
            cwd=ROOT / "desktop" / "src-tauri",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    bad = [
        f"{p['name']} {p['version']}: {p.get('license') or 'no license field'}"
        for p in meta["packages"]
        if p["name"] not in OWN and not acceptable(p.get("license") or "")
    ]
    if bad:
        print("Rust crates outside the allowed licenses:\n  " + "\n  ".join(bad))
        return 1
    print(f"rust licenses: {len(meta['packages']) - len(OWN)} crates ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
