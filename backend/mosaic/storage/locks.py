"""Advisory file locks (POSIX ``flock``) for one project's live directory.

- ``.open.lock``: every open ``Project`` holds it shared; relocating a project needs it
  exclusively, so a project is never moved while any process has it open.
- ``.checkpoint.lock``: snapshots of one live DB are serialized across threads and
  processes.

``flock`` locks belong to the open file description, so two opens in one process exclude
each other just as two processes do. On Windows (desktop, M3) these are no-ops for now.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]


class LockBusyError(RuntimeError):
    pass


class FileLock:
    def __init__(
        self, path: Path, *, exclusive: bool, blocking: bool, timeout_s: float = 0.0
    ) -> None:
        """``blocking`` waits indefinitely; otherwise retry for up to ``timeout_s``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[Any] | None = open(path, "a+")  # noqa: SIM115 - held until release
        if fcntl is None:
            return
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if blocking:
            fcntl.flock(self._fh.fileno(), flags)
            return
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(self._fh.fileno(), flags | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._fh.close()
                    self._fh = None
                    raise LockBusyError(str(path)) from None
                time.sleep(0.02)

    def downgrade(self) -> None:
        """Exclusive → shared, without a window in which another process could take it
        exclusively."""
        if self._fh is not None and fcntl is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_SH)

    def release(self) -> None:
        if self._fh is not None:
            if fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


@contextmanager
def locked(path: Path, *, exclusive: bool = True, blocking: bool = True) -> Iterator[None]:
    lock = FileLock(path, exclusive=exclusive, blocking=blocking)
    try:
        yield
    finally:
        lock.release()


def fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
