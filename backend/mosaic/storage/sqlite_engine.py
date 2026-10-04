"""SQLite-specific engine setup. All SQLite-only SQL lives in ``storage/sqlite_*``
(FUTURE_APPENDIX §1 guard)."""

from __future__ import annotations

from pathlib import Path

import sqlite_vec
from sqlalchemy import Engine, create_engine, event

from mosaic.storage.placement import assert_live_db_allowed


def make_engine(path: Path, *, wal: bool) -> Engine:
    """Open a live SQLite DB. Refuses network or cloud-synced locations (invariant 2)."""
    assert_live_db_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute(f"PRAGMA journal_mode={'WAL' if wal else 'DELETE'}")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
        # sqlite-vec for embedding search (ARCHITECTURE.md §12).
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    return engine
