"""The catalog of unsupported media (MEDIA_SUPPORT.md §1, invariant 14): every reason a
file is listed as unsupported, worded for the owner, with a suggested fix.

Profiles and the probe stage take their messages from here, so the same problem always
reads the same way. Entries are keyed by a stable code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Entry:
    code: str
    reason: str
    fix: str | None


CATALOG: dict[str, Entry] = {
    e.code: e
    for e in (
        Entry(
            "gopro_360",
            "GoPro MAX .360 files are not supported yet.",
            "Export a flat MP4 from GoPro Player.",
        ),
        Entry(
            "nikon_nraw",
            "Nikon N-RAW video cannot be decoded.",
            "Export H.264, HEVC or ProRes from NX Studio or your editor.",
        ),
        Entry(
            "insta360_photo_360",
            "Insta360 360° photos (.insp) are not supported yet.",
            "Export a flat JPEG from Insta360 Studio.",
        ),
        Entry(
            "insta360_raw_360",
            "Raw 360° footage is analyzed from a fixed forward view but cannot be placed in "
            "an edit yet.",
            "Export a reframed MP4 from Insta360 Studio to use it in edits.",
        ),
        Entry(
            "prores_raw",
            "ProRes RAW is not supported.",
            "Export ProRes 422 or HEVC from Final Cut Pro or your camera software.",
        ),
        Entry(
            "braw",
            "Blackmagic RAW (.braw) cannot be decoded.",
            "Export ProRes or H.264 from DaVinci Resolve.",
        ),
        Entry(
            "red_raw",
            "RED raw (.r3d) cannot be decoded.",
            "Export ProRes or H.264 from REDCINE-X or your editor.",
        ),
        Entry(
            "raw_not_v1",
            "This camera's raw photo format is not supported yet.",
            "Shoot RAW+JPEG, or export JPEGs from the camera maker's software.",
        ),
        Entry(
            "no_stream",
            "No playable video or audio stream.",
            "Check that the copy finished, or export the clip again.",
        ),
        Entry(
            "not_media",
            "Not a video, photo or audio file.",
            None,
        ),
    )
}

_BY_EXTENSION = {
    ".360": "gopro_360",
    ".nev": "nikon_nraw",
    ".insp": "insta360_photo_360",
    ".braw": "braw",
    ".r3d": "red_raw",
    ".cr3": "raw_not_v1",
    ".raf": "raw_not_v1",
    ".orf": "raw_not_v1",
    ".rw2": "raw_not_v1",
}


def unsupported_by_extension(path: str) -> Entry | None:
    code = _BY_EXTENSION.get(PurePosixPath(path).suffix.lower())
    return CATALOG[code] if code else None


def unsupported_codec(codec: str | None, tag: str | None = None) -> Entry | None:
    """Codecs MosAic does not support although a container names them (by codec name,
    or by codec tag when FFmpeg cannot name the codec)."""
    names = {(codec or "").lower(), (tag or "").lower()}
    if names & {"prores_raw", "aprn", "aprh"}:
        return CATALOG["prores_raw"]
    return None
