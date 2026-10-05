"""Photos (MEDIA_SUPPORT.md §2–3, ADR 0025): open JPEG, HEIC/HEIF, NEF and DNG read-only,
and describe them in the shape of an ffprobe result so camera profiles and grouping treat
photos and videos alike.

- **HEIC/HEIF** are decoded with pi-heif (libheif + libde265, LGPL, decode only).
- **NEF and DNG** use the camera's **embedded preview JPEG** (MEDIA_SUPPORT.md §2: fast,
  no raw decode). A minimal TIFF reader here finds it, together with the make, model,
  orientation and capture time.
- **Live Photos.** The Apple content identifier is read from the EXIF MakerNote and
  reported under the same tag name as the MOV's, so the iPhone profile pairs the two
  halves by identifier.

Originals are only ever opened for reading (invariant 1).
"""

from __future__ import annotations

import io
import struct
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from PIL import Image

RAW_EXT = frozenset({".nef", ".nrw", ".dng", ".arw", ".cr2"})  # TIFF-based raws
HEIF_EXT = frozenset({".heic", ".heif", ".hif"})
CONTENT_ID_TAG = "com.apple.quicktime.content.identifier"

# TIFF / EXIF tags
_MAKE, _MODEL, _ORIENTATION = 0x010F, 0x0110, 0x0112
_EXIF_IFD, _SUB_IFDS = 0x8769, 0x014A
_JPEG_OFFSET, _JPEG_LENGTH = 0x0201, 0x0202
_STRIP_OFFSETS, _STRIP_COUNTS, _COMPRESSION, _PHOTOMETRIC = 0x0111, 0x0117, 0x0103, 0x0106
_DATE_ORIGINAL, _OFFSET_ORIGINAL, _MAKER_NOTE = 0x9003, 0x9011, 0x927C
_APPLE_CONTENT_ID = 0x0011

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}
# Bounds for the IFD walk: a corrupt or hostile file can never hang or exhaust memory.
MAX_IFDS = 64
MAX_ENTRIES = 4096
MAX_SUB_IFDS = 16
MAX_VALUES = 1 << 16
MAX_TEXT = 1 << 12


class PhotoError(Exception):
    """The photo cannot be read; the message is shown to the owner."""


@dataclass(frozen=True)
class PhotoMeta:
    width: int  # display orientation
    height: int
    codec: str  # jpeg | heic | raw-preview | png | …
    make: str | None
    model: str | None
    capture_time: str | None  # ISO 8601; with an offset when the camera wrote one
    content_id: str | None


# --------------------------------------------------------------- TIFF reading


def _corrupt() -> PhotoError:
    return PhotoError("the raw file's structure is damaged")


class _Tiff:
    """Just enough TIFF to walk the IFDs of a raw file without reading pixel data. Every
    count and offset is checked against the file size."""

    def __init__(self, f: BinaryIO, size: int) -> None:
        self.f, self.size = f, size
        head = f.read(8)
        if len(head) < 8 or head[:2] not in (b"II", b"MM"):
            raise PhotoError("not a TIFF-based raw file")
        self.e = "<" if head[:2] == b"II" else ">"
        (magic, self.first_ifd) = struct.unpack(self.e + "HI", head[2:8])
        if magic != 42:
            raise PhotoError("not a TIFF-based raw file")

    def read(self, offset: int, n: int) -> bytes:
        if offset < 0 or n < 0 or offset + n > self.size:
            raise _corrupt()
        self.f.seek(offset)
        data = self.f.read(n)
        if len(data) != n:
            raise _corrupt()
        return data

    def ifd(self, offset: int) -> tuple[dict[int, tuple[int, int, bytes]], int]:
        """Entries ``tag → (type, count, value or offset bytes)`` and the next IFD."""
        (n,) = struct.unpack(self.e + "H", self.read(offset, 2))
        if n > MAX_ENTRIES:
            raise _corrupt()
        table = self.read(offset + 2, 12 * n + 4)
        entries = {}
        for i in range(n):
            tag, typ, count = struct.unpack(self.e + "HHI", table[12 * i : 12 * i + 8])
            entries[tag] = (typ, count, table[12 * i + 8 : 12 * i + 12])
        (nxt,) = struct.unpack(self.e + "I", table[12 * n :])
        return entries, nxt

    def _data(self, entry: tuple[int, int, bytes], limit: int) -> tuple[int, bytes]:
        typ, count, raw = entry
        count = min(count, limit)
        size = _TYPE_SIZE.get(typ, 1) * count
        if size <= 4:
            return count, raw[:size]
        (off,) = struct.unpack(self.e + "I", raw)
        return count, self.read(off, size)

    def values(self, entry: tuple[int, int, bytes], limit: int = MAX_VALUES) -> list[int]:
        typ = entry[0]
        count, data = self._data(entry, limit)
        if typ == 3:
            return list(struct.unpack(f"{self.e}{count}H", data))
        if typ in (4, 9, 13):
            return list(struct.unpack(f"{self.e}{count}I", data))
        return list(data)

    def first(self, entries: dict[int, tuple[int, int, bytes]], tag: int) -> int | None:
        if tag not in entries:
            return None
        vals = self.values(entries[tag], 1)
        return vals[0] if vals else None

    def text(self, entries: dict[int, tuple[int, int, bytes]], tag: int) -> str | None:
        if tag not in entries:
            return None
        _, data = self._data(entries[tag], MAX_TEXT)
        value = data.split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        return value or None


def _raw_scan(path: Path) -> tuple[bytes, dict[str, Any]]:
    """The largest embedded preview JPEG of a raw file, and its IFD0/EXIF metadata."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        t = _Tiff(f, size)
        seen: set[int] = set()
        queue: deque[int] = deque([t.first_ifd])
        previews: list[tuple[int, int]] = []
        meta: dict[str, Any] = {}
        first = True
        while queue:
            off = queue.popleft()
            if off == 0 or off in seen:
                continue
            if len(seen) >= MAX_IFDS:
                break
            seen.add(off)
            entries, nxt = t.ifd(off)
            if first:
                first = False
                meta["make"] = t.text(entries, _MAKE)
                meta["model"] = t.text(entries, _MODEL)
                meta["orientation"] = t.first(entries, _ORIENTATION)
                exif_at = t.first(entries, _EXIF_IFD)
                if exif_at:
                    exif, _ = t.ifd(exif_at)
                    meta["date"] = t.text(exif, _DATE_ORIGINAL)
                    meta["offset"] = t.text(exif, _OFFSET_ORIGINAL)
                if nxt:
                    queue.append(nxt)
            if _SUB_IFDS in entries:
                queue.extend(t.values(entries[_SUB_IFDS], MAX_SUB_IFDS))
            j_off, j_len = t.first(entries, _JPEG_OFFSET), t.first(entries, _JPEG_LENGTH)
            if j_off and j_len:
                previews.append((j_off, j_len))
            # A JPEG-compressed strip that is a picture (RGB/YCbCr), not raw sensor data.
            if t.first(entries, _COMPRESSION) in (6, 7) and t.first(entries, _PHOTOMETRIC) in (
                2,
                6,
            ):
                offs = t.values(entries[_STRIP_OFFSETS], 2) if _STRIP_OFFSETS in entries else []
                counts = t.values(entries[_STRIP_COUNTS], 2) if _STRIP_COUNTS in entries else []
                if len(offs) == 1 and len(counts) == 1:
                    previews.append((offs[0], counts[0]))
        for off, length in sorted(previews, key=lambda p: -p[1]):
            if off + length > size or length < 4:
                continue
            data = t.read(off, length)
            if data[:2] == b"\xff\xd8":
                return data, meta
    raise PhotoError("this raw file has no embedded preview image")


# ------------------------------------------------------------------- opening


def _register_heif() -> None:
    from pi_heif import register_heif_opener

    register_heif_opener()


_SWAPS = {5, 6, 7, 8}  # EXIF orientations that turn the picture by 90°


def _readable(fn: Any) -> Any:
    """Run a Pillow call; every failure becomes a ``PhotoError`` with an owner-facing
    reason, never an unhandled exception (invariant 14)."""
    try:
        return fn()
    except PhotoError:
        raise
    except (Image.DecompressionBombError, MemoryError):
        raise PhotoError("the photo is too large to read") from None
    except (OSError, ValueError, SyntaxError, struct.error, IndexError, KeyError, TypeError):
        raise PhotoError("the photo could not be read") from None


def _lazy(path: Path) -> tuple[Image.Image, dict[str, Any]]:
    """The photo opened without decoding pixels, and raw-file metadata."""
    ext = path.suffix.lower()
    if ext in RAW_EXT:
        data, meta = _readable(lambda: _raw_scan(path))
        return _readable(lambda: Image.open(io.BytesIO(data))), meta
    if ext in HEIF_EXT:
        _register_heif()
    return _readable(lambda: Image.open(path)), {}


def open_image(path: Path, short_side: int | None = None) -> tuple[Image.Image, dict[str, Any]]:
    """The photo decoded in display orientation, plus raw-file metadata. ``short_side``
    lets JPEG decoding scale down while decoding (``draft``), so a large photo never
    needs its full-size pixels in memory for analysis."""
    img, meta = _lazy(path)
    exif = _readable(img.getexif) if not meta else None
    raw_orientation = meta.get("orientation") or (exif.get(_ORIENTATION, 1) if exif else 1)
    orientation = raw_orientation if isinstance(raw_orientation, int) else 1

    def decode() -> Image.Image:
        if short_side and img.format == "JPEG":
            w, h = img.size
            scale = short_side / max(1, min(w, h))
            img.draft("RGB", (max(1, round(w * scale)), max(1, round(h * scale))))
        img.load()
        return _orient(img, orientation)

    return _readable(decode), meta


def _orient(img: Image.Image, orientation: int) -> Image.Image:
    ops = {
        2: [Image.Transpose.FLIP_LEFT_RIGHT],
        3: [Image.Transpose.ROTATE_180],
        4: [Image.Transpose.FLIP_TOP_BOTTOM],
        5: [Image.Transpose.TRANSPOSE],
        6: [Image.Transpose.ROTATE_270],
        7: [Image.Transpose.TRANSVERSE],
        8: [Image.Transpose.ROTATE_90],
    }
    for op in ops.get(orientation, []):
        img = img.transpose(op)
    return img


def _iso(date: Any, offset: Any) -> str | None:
    """EXIF ``YYYY:MM:DD HH:MM:SS`` (+ ``±HH:MM``) as ISO 8601; None when malformed. A
    time without an offset is local to the camera and stays naive (ADR 0025)."""
    date, offset = _str(date), _str(offset)
    if not date or len(date) < 19:
        return None
    text = date[:10].replace(":", "-") + "T" + date[11:19]
    if offset and len(offset) == 6 and offset[0] in "+-":
        text += offset
    try:
        return datetime.fromisoformat(text).isoformat(timespec="seconds")
    except ValueError:
        return None


def apple_content_id(maker_note: bytes | None) -> str | None:
    """The ContentIdentifier from an Apple EXIF MakerNote (``Apple iOS`` header, a big-
    endian IFD at offset 14 with offsets relative to the note)."""
    if not maker_note or not maker_note.startswith(b"Apple iOS\0"):
        return None
    try:
        f = io.BytesIO(maker_note)
        f.seek(14)
        (n,) = struct.unpack(">H", f.read(2))
        for _ in range(min(n, 256)):
            tag, typ, count = struct.unpack(">HHI", f.read(8))
            raw = f.read(4)
            if tag == _APPLE_CONTENT_ID and typ == 2:
                if count <= 4:
                    data = raw[:count]
                else:
                    (off,) = struct.unpack(">I", raw)
                    data = maker_note[off : off + count]
                value = data.split(b"\0", 1)[0].decode("ascii", "replace").strip()
                return value or None
    except struct.error:
        return None
    return None


def photo_meta(path: Path) -> PhotoMeta:
    """Size (as displayed), make, model, capture time and Live Photo identifier, read
    without decoding any pixels."""
    img, raw = _lazy(path)
    ext = path.suffix.lower()
    w, h = img.size
    if raw:
        if raw.get("orientation") in _SWAPS:
            w, h = h, w
        return PhotoMeta(
            w,
            h,
            "raw-preview",
            raw.get("make"),
            raw.get("model"),
            _iso(raw.get("date"), raw.get("offset")),
            None,
        )
    exif = _readable(img.getexif)
    if exif.get(_ORIENTATION) in _SWAPS:
        w, h = h, w
    sub = _readable(lambda: exif.get_ifd(_EXIF_IFD))
    note = sub.get(_MAKER_NOTE)
    return PhotoMeta(
        w,
        h,
        "heic" if ext in HEIF_EXT else (img.format or ext.lstrip(".")).lower(),
        _str(exif.get(_MAKE)),
        _str(exif.get(_MODEL)),
        _iso(sub.get(_DATE_ORIGINAL), sub.get(_OFFSET_ORIGINAL)),
        apple_content_id(note if isinstance(note, bytes) else None),
    )


def _str(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.split(b"\0", 1)[0].decode("utf-8", "replace")
    if not isinstance(value, str):
        return None
    return value.strip("\0 ").strip() or None


def photo_probe(path: Path) -> dict[str, Any]:
    """An ffprobe-shaped description of a photo (one picture "stream", no duration)."""
    meta = photo_meta(path)
    tags = {
        k: v
        for k, v in (
            ("make", meta.make),
            ("model", meta.model),
            ("creation_time", meta.capture_time),
            (CONTENT_ID_TAG, meta.content_id),
        )
        if v
    }
    return {
        "format": {"format_name": "image", "duration": "0", "tags": tags},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": meta.codec,
                "width": meta.width,
                "height": meta.height,
                "r_frame_rate": "0/0",
                "avg_frame_rate": "0/0",
                "time_base": "1/1",
                "start_pts": 0,
                "duration_ts": 0,
                "pix_fmt": "rgb24",
                "disposition": {"attached_pic": 0},
            }
        ],
    }
