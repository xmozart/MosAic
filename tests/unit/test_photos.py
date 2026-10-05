"""Photo reading (M1 step 9, ADR 0025): orientation, EXIF capture time with offset, Apple
content identifiers, raw previews and HEIC."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.media.photo import (
    CONTENT_ID_TAG,
    PhotoError,
    apple_content_id,
    open_image,
    photo_probe,
)
from tests.support.photos import HEIC, apple_maker_note, jpeg, raw_with_preview


def test_jpeg_metadata_and_orientation(tmp_path: Path) -> None:
    p = jpeg(
        tmp_path / "IMG_0001.JPG",
        make="Apple",
        model="iPhone 15 Pro",
        taken="2025:02:21 10:12:10",
        offset="+04:00",
        content_id="ABC-123",
        orientation=6,
    )
    d = photo_probe(p)
    tags = d["format"]["tags"]
    assert tags["make"] == "Apple"
    assert tags["creation_time"] == "2025-02-21T10:12:10+04:00"
    assert tags[CONTENT_ID_TAG] == "ABC-123"
    v = d["streams"][0]
    assert (v["width"], v["height"]) == (320, 480), "displayed upright"


def test_raw_uses_the_embedded_preview(tmp_path: Path) -> None:
    p = raw_with_preview(tmp_path / "DSC_0001.NEF", orientation=8)
    img, meta = open_image(p)
    assert (img.width, img.height) == (400, 640), "preview rotated by the raw's orientation"
    assert meta["make"] == "NIKON CORPORATION"
    d = photo_probe(p)
    assert d["format"]["tags"]["creation_time"] == "2025-03-01T10:00:00+01:00"
    assert d["streams"][0]["codec_name"] == "raw-preview"


def test_heic(tmp_path: Path) -> None:
    d = photo_probe(HEIC)
    assert (d["streams"][0]["width"], d["streams"][0]["height"]) == (320, 240)
    assert d["streams"][0]["codec_name"] == "heic"


def test_apple_content_identifier() -> None:
    assert apple_content_id(apple_maker_note("XYZ-9")) == "XYZ-9"
    assert apple_content_id(b"Nikon\0junk") is None
    assert apple_content_id(None) is None


def test_unreadable_photos_raise_a_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"\xff\xd8 not really")
    with pytest.raises(PhotoError):
        photo_probe(bad)
    raw = tmp_path / "x.NEF"
    raw.write_bytes(b"II*\0\x08\0\0\0\0\0\0\0\0\0")
    with pytest.raises(PhotoError):
        photo_probe(raw)


def _tiff(entries: list[tuple[int, int, int, int]], tail: bytes = b"") -> bytes:
    """A little-endian TIFF whose IFD0 holds ``(tag, type, count, value)`` entries."""
    import struct

    body = struct.pack("<H", len(entries))
    for tag, typ, count, value in entries:
        body += struct.pack("<HHII", tag, typ, count, value)
    return b"II" + struct.pack("<HI", 42, 8) + body + struct.pack("<I", 0) + tail


HOSTILE = {
    "zero_count_orientation": _tiff([(0x0112, 3, 0, 0)]),
    "zero_count_exif": _tiff([(0x8769, 4, 0, 0)]),
    "zero_count_jpeg": _tiff([(0x0201, 4, 0, 0), (0x0202, 4, 0, 0)]),
    "offset_past_eof": _tiff([(0x010F, 2, 64, 1 << 30)]),
    "huge_count": _tiff([(0x014A, 4, 0xFFFFFFFF, 8)]),
    "self_reference": _tiff([(0x014A, 4, 1, 8)]),
    "many_sub_ifds": _tiff([(0x014A, 4, 3_000_000, 26)], b"\x08\0\0\0" * 1000),
    "preview_past_eof": _tiff([(0x0201, 4, 1, 100), (0x0202, 4, 1, 1 << 30)]),
    "truncated": b"II*\0\x08\0\0\0\x05\0",
}


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_corrupt_raws_fail_cleanly_and_quickly(tmp_path: Path, case: str) -> None:
    import time

    p = tmp_path / f"{case}.NEF"
    p.write_bytes(HOSTILE[case])
    start = time.monotonic()
    with pytest.raises(PhotoError):
        photo_probe(p)
    assert time.monotonic() - start < 2, "never hangs"


def test_decompression_bomb_is_too_large(tmp_path: Path) -> None:
    from PIL import Image

    p = tmp_path / "bomb.png"
    Image.new("L", (100, 100)).save(p)
    old = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 1000  # a 10 000-pixel image is now twice past the limit
    try:
        with pytest.raises(PhotoError, match="too large"):
            open_image(p)
    finally:
        Image.MAX_IMAGE_PIXELS = old


def test_exif_time_edge_cases() -> None:
    from mosaic.media.photo import _iso

    assert _iso("2025:03:01 10:00:00", "+01:00") == "2025-03-01T10:00:00+01:00"
    assert _iso("2025:03:01 10:00:00", None) == "2025-03-01T10:00:00", "local, naive"
    assert _iso("2025:03:01 10:00:00", "garbage") == "2025-03-01T10:00:00"
    assert _iso("    :  :     :  :  ", "+01:00") is None
    assert _iso(b"2025:03:01 10:00:00\0", b"+02:00") == "2025-03-01T10:00:00+02:00"
    assert _iso(12345, None) is None
    assert _iso(None, None) is None


def test_probe_does_not_decode_pixels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    p = jpeg(tmp_path / "a.jpg", size=(400, 300), orientation=6)
    calls: list[int] = []
    real = Image.Image.load

    def counting(self: Image.Image) -> object:
        calls.append(1)
        return real(self)

    monkeypatch.setattr(Image.Image, "load", counting)
    monkeypatch.setattr("PIL.ImageFile.ImageFile.load", counting)
    d = photo_probe(p)
    assert (d["streams"][0]["width"], d["streams"][0]["height"]) == (300, 400)
    assert not calls, "size and EXIF only"


def test_other_raw_formats_are_unsupported_with_a_fix() -> None:
    from mosaic.media.unsupported import unsupported_by_extension

    for ext in (".CR3", ".raf", ".ORF", ".rw2"):
        entry = unsupported_by_extension(f"x{ext}")
        assert entry is not None
        assert "JPEG" in (entry.fix or "")
