"""SQLite-specific engine setup. All SQLite-only SQL lives in ``storage/sqlite_*``
(FUTURE_APPENDIX §1 guard)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec
from sqlalchemy import Connection, Engine, create_engine, event

from mosaic.storage.locks import fsync_file
from mosaic.storage.placement import assert_live_db_allowed

# Called with the path of every SQLite file MosAic opens read-write; a backup's read-only
# source is not reported. M1 acceptance 1 asserts with it that nothing on a network or
# cloud-synced folder is opened.
log = logging.getLogger(__name__)

OPEN_HOOKS: list[Callable[[Path], None]] = []


def _opened(path: Path) -> None:
    for hook in OPEN_HOOKS:
        hook(path)


def make_engine(path: Path, *, wal: bool) -> Engine:
    """Open a live SQLite DB. Refuses network or cloud-synced locations (invariant 2)."""
    assert_live_db_allowed(path)
    _opened(path)
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


def backup(src: Path, dst: Path, *, read_only_source: bool = False) -> None:
    """A consistent, self-contained copy of the SQLite DB ``src`` written to the new local
    file ``dst`` with the online backup API (safe while ``src`` is in use)."""
    import sqlite3

    assert_live_db_allowed(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    _opened(dst)
    if not read_only_source:
        _opened(src)
    if read_only_source:
        # A read-only folder: no -shm can be created, so read the file as immutable.
        source = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    else:
        source = sqlite3.connect(src)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")  # one file, no WAL beside it
        finally:
            target.close()
    finally:
        source.close()
    fsync_file(dst)


@contextmanager
def migration_transaction(conn: Connection) -> Iterator[None]:
    """One real transaction around a whole migration, with foreign keys off.

    The ``sqlite3`` driver commits DDL on its own outside a transaction it opened, so a
    failed upgrade could leave half its tables behind. Here the driver is put in
    autocommit mode and ``BEGIN`` is issued explicitly: every CREATE, DROP and ALTER is
    then inside it and rolls back with it. Foreign keys are off while a batch ``ALTER``
    rebuilds a table (copy, drop, rename; dropping a referenced table fails while they
    are on) and are checked before the commit."""
    raw = conn.connection.driver_connection
    if raw is None:
        raise RuntimeError("no driver connection for the migration")
    if conn.in_transaction():
        conn.commit()
    old = raw.isolation_level
    raw.isolation_level = None  # the driver no longer opens or commits on its own
    raw.execute("PRAGMA foreign_keys=OFF")
    try:
        # SQLAlchemy's transaction (Alembic joins it) ends with the driver's commit or
        # rollback, which ends this BEGIN.
        with conn.begin():
            raw.execute("BEGIN")
            yield
            bad = raw.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise MigrationIntegrityError(f"migration broke references: {bad[:5]}")
    finally:
        # Independent of how SQLAlchemy ended (a failed commit leaves the BEGIN open, and
        # the pragma is ignored inside a transaction): end it, turn foreign keys back on,
        # and never return a connection without them to the pool.
        fk_on = False
        try:
            if raw.in_transaction:
                raw.rollback()
            raw.execute("PRAGMA foreign_keys=ON")
            fk_on = raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        except Exception:  # cleanup failed: drop the connection, keep the first error
            log.exception("migration cleanup failed; discarding the connection")
        finally:
            raw.isolation_level = old
        if not fk_on:
            conn.invalidate()


class MigrationIntegrityError(RuntimeError):
    pass
