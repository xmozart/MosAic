"""Service container shared by API routes (and mirrored by the CLI)."""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from pathlib import Path

from mosaic.core.principal import Principal
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB


class Leases:
    """The project leases this server holds for open projects (``POST /projects/{pid}/open``),
    renewed in the background. A lease taken over by another computer is recorded as lost;
    the events stream reports it (``lock.lost``) and the project becomes read-only here."""

    def __init__(self, control: ControlDB) -> None:
        self.control = control
        self.held: dict[str, Path] = {}  # project id → its lease folder
        self.read_only: set[str] = set()
        self.lost: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def hold(self, project_id: str, folder: Path) -> None:
        with self._lock:
            self.held[project_id] = folder
            self.read_only.discard(project_id)
            self.lost.discard(project_id)
            if self._thread is None:
                self._thread = threading.Thread(target=self._renew_loop, daemon=True)
                self._thread.start()

    def open_read_only(self, project_id: str) -> None:
        with self._lock:
            self.held.pop(project_id, None)
            self.read_only.add(project_id)
            self.lost.discard(project_id)  # the user accepted read-only: reported once

    def drop(self, project_id: str) -> Path | None:
        with self._lock:
            self.read_only.discard(project_id)
            self.lost.discard(project_id)
            return self.held.pop(project_id, None)

    def renew_all(self) -> None:
        import logging

        from mosaic.storage import lease

        with self._lock:
            held = dict(self.held)
        for pid, folder in held.items():
            try:
                ok = lease.renew(folder, self.control.installation_id)
            except OSError:
                continue  # an offline share: try again next round
            except Exception:
                logging.getLogger(__name__).exception("renewing the lease of %s failed", pid)
                continue
            if not ok:
                with self._lock:
                    self.held.pop(pid, None)
                    self.lost.add(pid)
                    self.read_only.add(pid)

    def _renew_loop(self) -> None:
        import logging

        from mosaic.storage.lease import RENEW_AFTER_S

        while not self._stop.wait(RENEW_AFTER_S):
            try:
                self.renew_all()
            except Exception:  # the thread must outlive any one failure
                logging.getLogger(__name__).exception("lease renewal round failed")

    def shutdown(self) -> None:
        """Stop renewing and release every lease this server holds."""
        from mosaic.storage import lease

        self._stop.set()
        with self._lock:
            held = dict(self.held)
            self.held.clear()
        for folder in held.values():
            with contextlib.suppress(OSError):  # unreachable: it lapses on its own
                lease.release(folder, self.control.installation_id)


@dataclass
class Services:
    control: ControlDB
    store: JobStore
    executor: LocalExecutor
    leases: Leases = field(init=False)

    def __post_init__(self) -> None:
        self.leases = Leases(self.control)

    @classmethod
    def create(cls, control: ControlDB | None = None) -> Services:
        control = control or ControlDB()
        store = JobStore(control.db)
        return cls(control, store, LocalExecutor(store))

    @property
    def principal(self) -> Principal:
        return self.control.local_principal
