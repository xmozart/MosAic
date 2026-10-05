"""Synthetic photos for tests: JPEGs with EXIF (Apple MakerNote content identifiers), a
TIFF-based raw with an embedded preview JPEG, and the committed tiny HEIC (ADR 0025)."""

from __future__ import annotations

import io
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from mosaic.devtools.corpus import render_frame

HEIC = Path(__file__).parents[1] / "fixtures" / "media" / "tiny_320x240.heic"


def apple_maker_note(content_id: str) -> bytes:
    """An Apple ``iOS`` MakerNote holding ContentIdentifier (tag 0x0011, ASCII)."""
    value = content_id.encode() + b"\0"
    head = b"Apple iOS\0" + b"\x00\x01" + b"MM"
    ifd_at = len(head)
    data_at = ifd_at + 2 + 12 + 4
    entry = struct.pack(">HHI", 0x0011, 2, len(value)) + struct.pack(">I", data_at)
    return head + struct.pack(">H", 1) + entry + struct.pack(">I", 0) + value


def jpeg(
    path: Path,
    *,
    seed: int = 1,
    size: tuple[int, int] = (480, 320),
    make: str | None = None,
    model: str | None = None,
    taken: str | None = None,
    offset: str | None = None,
    content_id: str | None = None,
    orientation: int | None = None,
) -> Path:
    img = Image.fromarray(render_frame(size[0], size[1], seed, 1, seed))
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
    if model:
        exif[0x0110] = model
    if orientation:
        exif[0x0112] = orientation
    sub = exif.get_ifd(0x8769)
    if taken:
        sub[0x9003] = taken
    if offset:
        sub[0x9011] = offset
    if content_id:
        sub[0x927C] = apple_maker_note(content_id)
    img.save(path, exif=exif.tobytes(), quality=90)
    return path


def raw_with_preview(
    path: Path,
    *,
    make: str = "NIKON CORPORATION",
    model: str = "NIKON Z 6_2",
    orientation: int = 1,
    taken: str = "2025:03:01 10:00:00",
    offset: str = "+01:00",
    seed: int = 3,
) -> Path:
    """A little-endian TIFF shaped like a NEF: IFD0 (make, model, orientation, EXIF and a
    SubIFD pointer) and a SubIFD holding a full-size preview JPEG."""
    preview = io.BytesIO()
    Image.fromarray(render_frame(640, 400, seed, 1, seed)).save(preview, "JPEG", quality=90)
    jpg = preview.getvalue()
    e = "<"

    def ifd(entries: list[tuple[int, int, int, bytes | int]], at: int) -> tuple[bytes, bytes]:
        """IFD bytes placed at ``at`` and the out-of-line data that follows it."""
        n = len(entries)
        data_at = at + 2 + 12 * n + 4
        table, extra = struct.pack(e + "H", n), b""
        for tag, typ, count, value in entries:
            if isinstance(value, int):
                table += struct.pack(e + "HHII", tag, typ, count, value)
            elif len(value) <= 4:
                table += struct.pack(e + "HHI", tag, typ, count) + value.ljust(4, b"\0")
            else:
                table += struct.pack(e + "HHII", tag, typ, count, data_at + len(extra))
                extra += value
        return table + struct.pack(e + "I", 0), extra

    make_b, model_b = make.encode() + b"\0", model.encode() + b"\0"
    date_b, off_b = taken.encode() + b"\0", offset.encode() + b"\0"
    # Layout: header | IFD0 + data | EXIF IFD + data | SubIFD + data | JPEG
    ifd0_at = 8
    probe0, extra0 = ifd(
        [
            (0x010F, 2, len(make_b), make_b),
            (0x0110, 2, len(model_b), model_b),
            (0x0112, 3, 1, struct.pack(e + "H", orientation)),
            (0x8769, 4, 1, 0),
            (0x014A, 4, 1, 0),
        ],
        ifd0_at,
    )
    exif_at = ifd0_at + len(probe0) + len(extra0)
    exif_tbl, exif_extra = ifd(
        [(0x9003, 2, len(date_b), date_b), (0x9011, 2, len(off_b), off_b)], exif_at
    )
    sub_at = exif_at + len(exif_tbl) + len(exif_extra)
    sub_len = 2 + 12 * 2 + 4
    jpg_at = sub_at + sub_len
    sub_tbl, _ = ifd([(0x0201, 4, 1, jpg_at), (0x0202, 4, 1, len(jpg))], sub_at)
    ifd0, extra0 = ifd(
        [
            (0x010F, 2, len(make_b), make_b),
            (0x0110, 2, len(model_b), model_b),
            (0x0112, 3, 1, struct.pack(e + "H", orientation)),
            (0x8769, 4, 1, exif_at),
            (0x014A, 4, 1, sub_at),
        ],
        ifd0_at,
    )
    blob = b"II" + struct.pack(e + "HI", 42, ifd0_at) + ifd0 + extra0
    blob += exif_tbl + exif_extra + sub_tbl + jpg
    assert np.frombuffer(blob[jpg_at : jpg_at + 2], dtype=np.uint8).tolist() == [0xFF, 0xD8]
    path.write_bytes(blob)
    return path
