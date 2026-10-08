"""Storage placement policy (ARCHITECTURE.md §4): classify a folder's filesystem and
choose where the live project data goes (``storage/projects.py``, ADR 0022)."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class FsClass(StrEnum):
    LOCAL = "local"
    NETWORK = "network"
    CLOUD_SYNCED = "cloud_synced"
    READ_ONLY = "read_only"


class Placement(StrEnum):
    IN_FOLDER = "in_folder"
    SPLIT = "split"
    EXTERNAL = "external"


PLACEMENT_FOR_CLASS = {
    FsClass.LOCAL: Placement.IN_FOLDER,
    FsClass.NETWORK: Placement.SPLIT,
    FsClass.CLOUD_SYNCED: Placement.SPLIT,
    FsClass.READ_ONLY: Placement.EXTERNAL,
}

NETWORK_FS_TYPES = frozenset(
    {
        "smbfs",
        "nfs",
        "nfs4",
        "afpfs",
        "webdav",
        "cifs",
        "smb3",
        "smb2",
        "9p",
        "sshfs",
        "fuse.sshfs",
        "davfs",
        "fuse.rclone",
    }
)

# A host folder shared into a VM or container (Docker Desktop, Podman machine, VirtualBox,
# Parallels). What backs it (a NAS, a cloud-synced folder) can't be seen from inside, so
# it is treated like a network share: never a live database there (invariant 2; ADR 0055).
HOST_SHARE_FS_TYPES = frozenset(
    {
        "virtiofs",
        "fakeowner",
        "grpcfuse",
        "fuse.grpcfuse",
        "osxfs",
        "fuse.osxfs",
        "vboxsf",
        "prl_fs",
    }
)
# ``never``: a live database never goes in a footage folder, whatever it looks like (the
# server image sets it: a bind mount can't be trusted to reveal its storage; ADR 0055).
ENV_FOLDER_DB = "MOSAIC_FOLDER_DB"

_CLOUD_MARKERS = (
    ("Library", "Mobile Documents"),  # iCloud Drive
    ("Library", "CloudStorage"),  # File Provider: OneDrive, Google Drive, Dropbox, Box
)
_CLOUD_ROOT_EXACT = frozenset(
    {"Dropbox", "OneDrive", "Google Drive", "iCloudDrive", "Box", "Box Sync", "pCloud Drive"}
)
_CLOUD_ROOT_PREFIXES = ("Dropbox (", "OneDrive - ", "OneDrive-")
# TODO(M1, Windows desktop): detect Windows cloud-file attributes (ARCHITECTURE.md §4).


@dataclass(frozen=True)
class Classification:
    fs_class: FsClass
    placement: Placement
    fs_type: str
    reason: str


class PlacementRefusedError(RuntimeError):
    """A placement the folder's storage class does not allow (invariant 2)."""


def _macos_fs_type(path: Path) -> str | None:
    """``f_fstypename`` from macOS ``statfs(2)``."""

    class Statfs(ctypes.Structure):
        _fields_ = [
            ("f_bsize", ctypes.c_uint32),
            ("f_iosize", ctypes.c_int32),
            ("f_blocks", ctypes.c_uint64),
            ("f_bfree", ctypes.c_uint64),
            ("f_bavail", ctypes.c_uint64),
            ("f_files", ctypes.c_uint64),
            ("f_ffree", ctypes.c_uint64),
            ("f_fsid", ctypes.c_int32 * 2),
            ("f_owner", ctypes.c_uint32),
            ("f_type", ctypes.c_uint32),
            ("f_flags", ctypes.c_uint32),
            ("f_fssubtype", ctypes.c_uint32),
            ("f_fstypename", ctypes.c_char * 16),
            ("f_mntonname", ctypes.c_char * 1024),
            ("f_mntfromname", ctypes.c_char * 1024),
            ("f_flags_ext", ctypes.c_uint32),
            ("f_reserved", ctypes.c_uint32 * 7),
        ]

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    fn = libc.statfs64 if hasattr(libc, "statfs64") else libc.statfs
    buf = Statfs()
    if fn(os.fsencode(str(path)), ctypes.byref(buf)) != 0:
        return None
    name: bytes = buf.f_fstypename
    return name.decode(errors="replace")


def _linux_fs_type(path: Path) -> str | None:
    try:
        mounts = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return None
    best, best_type = "", None
    target = str(path)
    for line in mounts:
        parts = line.split()
        if len(parts) < 3:
            continue
        mnt = parts[1].replace("\\040", " ")
        if (target == mnt or target.startswith(mnt.rstrip("/") + "/")) and len(mnt) > len(best):
            best, best_type = mnt, parts[2]
    return best_type


def _windows_is_remote(path: Path) -> bool:
    drive = os.path.splitdrive(str(path))[0]
    if drive.startswith("\\\\"):
        return True
    get_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
    return bool(get_type(drive + "\\") == 4)  # DRIVE_REMOTE


def fs_type(path: Path) -> str:
    if sys.platform == "darwin":
        return _macos_fs_type(path) or "unknown"
    if sys.platform.startswith("linux"):
        return _linux_fs_type(path) or "unknown"
    if os.name == "nt":
        return "remote" if _windows_is_remote(path) else "local"
    return "unknown"


def is_cloud_synced(path: Path, home: Path | None = None) -> bool:
    home = home or Path.home()
    try:
        rel = path.relative_to(home)
    except ValueError:
        return False
    parts = rel.parts
    for marker in _CLOUD_MARKERS:
        if parts[: len(marker)] == marker:
            return True
    if not parts:
        return False
    return parts[0] in _CLOUD_ROOT_EXACT or parts[0].startswith(_CLOUD_ROOT_PREFIXES)


def is_writable(path: Path) -> bool:
    """Non-mutating write check: no probe file is created in the footage folder (ADR 0005)."""
    return os.access(path, os.W_OK | os.X_OK)


def classify(path: Path, *, home: Path | None = None) -> Classification:
    path = path.resolve()
    ftype = fs_type(path)
    if is_cloud_synced(path, home):
        cls, reason = FsClass.CLOUD_SYNCED, "folder is inside a cloud-synced location"
    elif ftype in NETWORK_FS_TYPES or ftype == "remote":
        cls, reason = FsClass.NETWORK, f"folder is on a network filesystem ({ftype})"
    elif ftype in HOST_SHARE_FS_TYPES:
        cls, reason = (
            FsClass.NETWORK,
            f"folder is shared in from the host ({ftype}); its storage can't be seen",
        )
    elif not is_writable(path):
        cls, reason = FsClass.READ_ONLY, "folder is not writable"
    else:
        cls, reason = FsClass.LOCAL, f"local filesystem ({ftype})"
    placement = PLACEMENT_FOR_CLASS[cls]
    if placement is Placement.IN_FOLDER and folder_db_forbidden():
        placement = Placement.SPLIT
        reason += f"; the live database stays in app data ({ENV_FOLDER_DB}=never)"
    return Classification(cls, placement, ftype, reason)


def folder_db_forbidden() -> bool:
    return os.environ.get(ENV_FOLDER_DB, "").strip().lower() == "never"


def assert_live_db_allowed(db_path: Path) -> None:
    """Invariant 2: never place a live SQLite database on network or cloud-synced storage."""
    probe = db_path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    c = classify(probe)
    if c.fs_class in (FsClass.NETWORK, FsClass.CLOUD_SYNCED):
        raise PlacementRefusedError(f"refusing to open a live database at {db_path}: {c.reason}")
    if folder_db_forbidden():
        from mosaic.core.paths import app_data_dir

        home = app_data_dir().resolve()
        target = probe.resolve()
        if target != home and home not in target.parents:
            raise PlacementRefusedError(
                f"refusing to open a live database at {db_path}: {ENV_FOLDER_DB}=never keeps "
                "live databases in app data"
            )
