"""Artifact store (ARCHITECTURE.md §4): code asks for ``(kind, key)``, never builds paths.

Blobs live under the store root (``<root>/MosAic/cache`` for in-folder placement). The
project DB ``artifact`` table indexes them, so ``exists`` means "written completely and
recorded". Writes go to a temp file and are renamed into place. Every artifact links to a
provenance row (invariant 9).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.storage.db import Database
from mosaic.storage.models_project import Artifact

_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ArtifactMissingError(KeyError):
    pass


def _check_name(kind: str, key: str) -> None:
    for part in (kind, key):
        if not _SAFE.match(part) or ".." in part:
            raise ValueError(f"unsafe artifact kind/key: {kind!r}/{key!r}")


def dumps_json(value: Any) -> bytes:
    """Stable JSON for stored blobs (values are kept as-is; unlike key hashing)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class NestedWriteError(RuntimeError):
    """An artifact was recorded inside an open project write session (would deadlock)."""


class WriteGate:
    """One writer per project (ARCHITECTURE.md §7): a lock shared by project write sessions
    and artifact recording, plus a per-thread flag that catches nested writes."""

    def __init__(self) -> None:
        self.lock = threading.Lock()  # nesting is refused before acquiring, never re-entered
        self._local = threading.local()

    @property
    def active(self) -> bool:
        return bool(getattr(self._local, "active", False))

    @contextmanager
    def hold(self) -> Iterator[None]:
        if self.active:
            raise NestedWriteError(
                "nested project write: finish the open write session before writing again"
            )
        with self.lock:
            self._local.active = True
            try:
                yield
            finally:
                self._local.active = False


class ArtifactStore:
    def __init__(self, root: Path, db: Database, gate: WriteGate | None = None) -> None:
        self.root = root
        self.db = db
        self.gate = gate or WriteGate()
        self.root.mkdir(parents=True, exist_ok=True)

    def _relpath(self, kind: str, key: str, ext: str) -> str:
        return f"{kind}/{key[-2:]}/{key}{ext}"

    def _row(self, key: str) -> Artifact | None:
        with self.db.session() as s:
            return s.get(Artifact, key)

    def exists(self, kind: str, key: str) -> bool:
        row = self._row(key)
        if row is None or row.kind != kind:
            return False
        path = self.root / row.location
        return path.is_file() and path.stat().st_size == row.size

    def path(self, kind: str, key: str) -> Path:
        """Local path of an existing artifact (for subprocesses such as FFmpeg)."""
        row = self._row(key)
        if row is None or row.kind != kind:
            raise ArtifactMissingError(f"{kind}/{key}")
        return self.root / row.location

    def provenance_id(self, kind: str, key: str) -> int:
        row = self._row(key)
        if row is None or row.kind != kind:
            raise ArtifactMissingError(f"{kind}/{key}")
        return row.provenance_id

    @contextmanager
    def writer(self, kind: str, key: str, ext: str, *, provenance_id: int) -> Iterator[Path]:
        """Yield a temp path to write; on success it is moved into place and recorded."""
        _check_name(kind, key)
        if self.gate.active:
            raise NestedWriteError(f"artifact {kind}/{key} written inside a write session")
        rel = self._relpath(kind, key, ext)
        final = self.root / rel
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.with_name(f".{final.name}.{uuid.uuid4().hex}.tmp{ext}")
        try:
            yield tmp
            if not tmp.exists():
                raise RuntimeError(f"artifact writer for {kind}/{key} produced no file")
            os.replace(tmp, final)
        finally:
            if tmp.exists():
                tmp.unlink()
        self._record(kind, key, rel, final.stat().st_size, provenance_id)

    def _record(self, kind: str, key: str, rel: str, size: int, prov: int) -> None:
        with self.gate.hold(), self.db.session() as s:
            row = s.get(Artifact, key)
            if row is None:
                s.add(
                    Artifact(
                        key=key,
                        kind=kind,
                        location=rel,
                        size=size,
                        provenance_id=prov,
                        created_at=now_iso(),
                    )
                )
            else:
                row.location, row.size, row.provenance_id = rel, size, prov

    def put_bytes(
        self, kind: str, key: str, data: bytes, *, provenance_id: int, ext: str = ".bin"
    ) -> None:
        with self.writer(kind, key, ext, provenance_id=provenance_id) as tmp:
            tmp.write_bytes(data)

    def put_json(self, kind: str, key: str, value: Any, *, provenance_id: int) -> None:
        self.put_bytes(kind, key, dumps_json(value), provenance_id=provenance_id, ext=".json")

    def put_file(self, kind: str, key: str, src: Path, *, provenance_id: int) -> None:
        with self.writer(kind, key, src.suffix, provenance_id=provenance_id) as tmp:
            shutil.copyfile(src, tmp)

    def get_bytes(self, kind: str, key: str) -> bytes:
        return self.path(kind, key).read_bytes()

    def get_json(self, kind: str, key: str) -> Any:
        return json.loads(self.get_bytes(kind, key))

    def delete(self, kind: str, key: str) -> None:
        with self.gate.hold(), self.db.session() as s:
            row = s.get(Artifact, key)
            if row is None or row.kind != kind:
                return
            (self.root / row.location).unlink(missing_ok=True)
            s.delete(row)

    def keys(self, kind: str) -> list[str]:
        with self.db.session() as s:
            return list(s.scalars(select(Artifact.key).where(Artifact.kind == kind)))
