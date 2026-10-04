"""Folder scan (MEDIA_SUPPORT.md §5): find files, classify by type, fingerprint.

Source files are only ever opened for reading (invariant 1). Files that are cloud
placeholders are reported as offline and never read, so a scan cannot trigger a download.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mosaic.core.paths import DESCRIPTOR_NAME, WORKSPACE_DIR


class MediaType(StrEnum):
    VIDEO = "video"
    PHOTO = "photo"
    AUDIO = "audio"
    SIDECAR = "sidecar"
    OTHER = "other"


VIDEO_EXT = frozenset(
    {
        ".mp4",
        ".mov",
        ".m4v",
        ".mts",
        ".m2ts",
        ".avi",
        ".mkv",
        ".webm",
        ".insv",
        ".360",
        ".3gp",
        ".mpg",
        ".mpeg",
        ".wmv",
        ".mxf",
        ".nev",
    }
)
PHOTO_EXT = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".heic",
        ".heif",
        ".png",
        ".dng",
        ".nef",
        ".nrw",
        ".arw",
        ".cr2",
        ".cr3",
        ".raf",
        ".orf",
        ".rw2",
        ".tif",
        ".tiff",
        ".webp",
        ".insp",
        ".avif",
        ".gif",
    }
)
AUDIO_EXT = frozenset(
    {".wav", ".m4a", ".mp3", ".aac", ".flac", ".aif", ".aiff", ".ogg", ".opus", ".caf"}
)
SIDECAR_EXT = frozenset({".lrf", ".lrv", ".thm", ".srt", ".xmp", ".aae"})
IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", DESCRIPTOR_NAME, "Icon\r"})

SF_DATALESS = 0x40000000  # macOS: file content is not local (iCloud/File Provider)
FINGERPRINT_CHUNK = 64 * 1024


def media_type_for(path: Path) -> MediaType:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return MediaType.VIDEO
    if ext in PHOTO_EXT:
        return MediaType.PHOTO
    if ext in AUDIO_EXT:
        return MediaType.AUDIO
    if ext in SIDECAR_EXT:
        return MediaType.SIDECAR
    return MediaType.OTHER


@dataclass(frozen=True)
class ScannedFile:
    rel_path: str  # POSIX-style, relative to the project root
    size: int
    mtime_ns: int
    media_type: MediaType
    offline: bool


def is_offline(st: os.stat_result) -> bool:
    flags = getattr(st, "st_flags", 0)
    return bool(flags & SF_DATALESS)


def scan(root: Path) -> Iterator[ScannedFile]:
    """Walk ``root`` in sorted order, skipping the workspace, hidden and system entries.

    Symlinks are not followed, so the scan never leaves the project root.
    """
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and not (here == root and d == WORKSPACE_DIR)
        )
        for name in sorted(filenames):
            if name.startswith(".") or name in IGNORED_NAMES:
                continue
            path = here / name
            try:
                st = path.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            yield ScannedFile(
                rel_path=path.relative_to(root).as_posix(),
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                media_type=media_type_for(path),
                offline=is_offline(st),
            )


def fingerprint(path: Path, size: int) -> str:
    """Fast fingerprint: size plus a hash of the first and last 64 KiB (read-only open)."""
    h = hashlib.sha256()
    h.update(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(FINGERPRINT_CHUNK))
        if size > FINGERPRINT_CHUNK:
            f.seek(max(size - FINGERPRINT_CHUNK, FINGERPRINT_CHUNK))
            h.update(f.read(FINGERPRINT_CHUNK))
    return f"{size}-{h.hexdigest()[:32]}"
