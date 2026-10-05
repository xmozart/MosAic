"""Project leases (ARCHITECTURE.md §14, ADR 0023): one MosAic installation edits a
project at a time.

The lease file ``.lock`` lives in the project's outputs folder (``<root>/MosAic`` for in-
folder and split projects), so every computer that can see the footage sees it. It names
the holder (an installation id), host, pid and an expiry. A lease is renewed while the
project is in use and lapses on its own when the holder stops without releasing it.

- Processes of one installation (app, CLI, worker) share the lease.
- A read-only open never takes it.
- An expired lease can be taken over. A live one only with ``force`` (the UI warns first).

Expiry is the writer's wall-clock time: computers whose clocks differ by more than the
renewal margin (``LEASE_TTL_S - RENEW_AFTER_S``, about 3 minutes) can misjudge a live
lease as expired. Desktop clocks are network-synchronized; ADR 0023 records the limit.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

LEASE_FILE = ".lock"
LEASE_TTL_S = 300
RENEW_AFTER_S = LEASE_TTL_S // 3  # renewals closer together than this are skipped


@dataclass(frozen=True)
class Lease:
    holder: str  # installation id
    host: str
    pid: int
    acquired_at: str
    expires_at: str

    def expired(self, now: datetime | None = None) -> bool:
        return datetime.fromisoformat(self.expires_at) <= (now or datetime.now(UTC))

    def remaining_s(self) -> float:
        return (datetime.fromisoformat(self.expires_at) - datetime.now(UTC)).total_seconds()


class LeaseHeldError(RuntimeError):
    """The project is open for editing on another computer."""

    def __init__(self, lease: Lease) -> None:
        super().__init__(
            f"this project is open on {lease.host} (until {lease.expires_at[:16]} UTC unless "
            "renewed). Open it read-only, or take it over (the other computer then loses "
            "edit access)."
        )
        self.lease = lease


def read(folder: Path) -> Lease | None:
    """The lease, or None when there is none (or the file is corrupt). An unreadable
    folder raises ``OSError``: "cannot read" must never be taken as "free"."""
    try:
        text = (folder / LEASE_FILE).read_text()
    except FileNotFoundError:
        return None
    try:
        return Lease(**json.loads(text))
    except (ValueError, TypeError):
        return None


def _write(folder: Path, lease: Lease) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f"{LEASE_FILE}.{uuid.uuid4().hex}.part"
    try:
        part.write_text(json.dumps(asdict(lease)))
        os.replace(part, folder / LEASE_FILE)
    finally:
        part.unlink(missing_ok=True)


def _new(holder: str, acquired_at: str | None = None) -> Lease:
    now = datetime.now(UTC)
    return Lease(
        holder=holder,
        host=socket.gethostname(),
        pid=os.getpid(),
        acquired_at=acquired_at or now.isoformat(timespec="seconds"),
        expires_at=(now + timedelta(seconds=LEASE_TTL_S)).isoformat(timespec="seconds"),
    )


def acquire(folder: Path, holder: str, *, force: bool = False) -> Lease:
    """Take or renew the lease. Raises ``LeaseHeldError`` if another installation holds a
    live one (unless ``force``). After writing, the file is read back: when two computers
    race, the last writer wins and the other gets the error."""
    current = read(folder)
    if current is not None and current.holder != holder and not current.expired() and not force:
        raise LeaseHeldError(current)
    mine = current.holder == holder if current else False
    if mine and current is not None and current.remaining_s() > LEASE_TTL_S - RENEW_AFTER_S:
        return current  # renewed recently: skip a write (network folders)
    lease = _new(holder, current.acquired_at if mine and current else None)
    _write(folder, lease)
    back = read(folder)
    if back is None or back.holder != holder:
        raise LeaseHeldError(back or lease)
    return back


def renew(folder: Path, holder: str) -> bool:
    """Extend our lease. False when another installation holds a live one (it was taken
    over: the caller lost edit access). Never forces, so a takeover is never undone."""
    try:
        acquire(folder, holder)
    except LeaseHeldError:
        return False
    return True


def release(folder: Path, holder: str) -> None:
    current = read(folder)
    if current is not None and current.holder == holder:
        (folder / LEASE_FILE).unlink(missing_ok=True)
