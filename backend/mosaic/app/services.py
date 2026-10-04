"""Service container shared by API routes (and mirrored by the CLI)."""

from __future__ import annotations

from dataclasses import dataclass

from mosaic.core.principal import Principal
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB


@dataclass
class Services:
    control: ControlDB
    store: JobStore
    executor: LocalExecutor

    @classmethod
    def create(cls, control: ControlDB | None = None) -> Services:
        control = control or ControlDB()
        store = JobStore(control.db)
        return cls(control, store, LocalExecutor(store))

    @property
    def principal(self) -> Principal:
        return self.control.local_principal
