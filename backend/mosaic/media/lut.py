"""User LUTs for log footage (ARCHITECTURE.md §10, MEDIA_SUPPORT.md §2; ADR 0028).

A device's LUT is an Adobe/Resolve ``.cube`` 3D LUT supplied by the owner (vendor LUTs
are not redistributed). It is validated, copied into the project's artifact store keyed
by its content, and applied with FFmpeg's ``lut3d`` filter (LGPL) to that device's
proxies and final renders.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

MAX_SIZE = 65  # LUT_3D_SIZE beyond this is not a camera LUT
MAX_BYTES = 64 * 1024 * 1024


class LutError(ValueError):
    """The file is not a usable 3D .cube LUT; the message is shown to the owner."""


def check_cube(path: Path) -> int:
    """Validate a 3D ``.cube`` file and return its size (points per axis)."""
    if path.suffix.lower() != ".cube":
        raise LutError("a LUT must be a .cube file")
    try:
        if path.stat().st_size > MAX_BYTES:
            raise LutError("the LUT file is too large")
        lines = path.read_text(errors="replace").splitlines()
    except OSError as exc:
        raise LutError(f"cannot read the LUT: {exc.strerror or exc}") from None
    size = None
    rows = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head == "LUT_3D_SIZE":
            try:
                size = int(line.split()[1])
            except (IndexError, ValueError):
                raise LutError("LUT_3D_SIZE is not a number") from None
        elif head == "LUT_1D_SIZE":
            raise LutError("1D LUTs are not supported; use a 3D .cube LUT")
        elif head[0].isdigit() or head[0] in "-.":
            parts = line.split()
            try:
                if len(parts) != 3:
                    raise ValueError
                [float(p) for p in parts]
            except ValueError:
                raise LutError(f"not a LUT row: {line[:40]!r}") from None
            rows += 1
    if size is None or not 2 <= size <= MAX_SIZE:
        raise LutError("missing or unusual LUT_3D_SIZE (2–65)")
    if rows != size**3:
        raise LutError(f"expected {size**3} rows for a {size}³ LUT, found {rows}")
    return size


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lut_key(content_digest: str) -> str:
    return f"lut-{content_digest[:32]}"
