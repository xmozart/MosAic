"""SQLite engines, sessions and migrations for the control DB and project DBs."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from mosaic.storage.sqlite_engine import make_engine, migration_transaction

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
Tree = Literal["control", "project"]


def alembic_config(tree: Tree, url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("script_location", str(MIGRATIONS / tree))
    cfg.set_main_option("version_locations", str(MIGRATIONS / tree / "versions"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


# Alembic's migration context is process-global: two threads upgrading at once (two
# requests opening a project together) corrupt each other's run.
_MIGRATE_LOCK = threading.Lock()


@lru_cache(maxsize=2)
def head_revision(tree: Tree) -> str | None:
    """The tree's newest migration (read once per process)."""
    return ScriptDirectory.from_config(alembic_config(tree)).get_current_head()


def at_head(engine: Engine, tree: Tree) -> bool:
    """The database already has the newest schema: one row read, no migration run."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    except OperationalError:  # a new database: no version table yet
        return False
    return [r[0] for r in rows] == [head_revision(tree)]


def migrate(engine: Engine, tree: Tree) -> None:
    """Upgrade to head in one real transaction: a failure leaves the DB as it was. One
    migration runs at a time in this process. A database already at head is left alone:
    the full check (Alembic, then a foreign-key scan of every table) cost most of a
    request that opens a project (40 ms of the 40-hour library page; ADR 0064)."""
    if at_head(engine, tree):
        return
    cfg = alembic_config(tree)
    with _MIGRATE_LOCK, engine.connect() as conn, migration_transaction(conn):
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


class Database:
    """An engine plus a session factory."""

    def __init__(self, path: Path, tree: Tree, *, wal: bool = True) -> None:
        self.path = path
        self.tree = tree
        self.engine = make_engine(path, wal=wal)
        migrate(self.engine, tree)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as s:
            try:
                yield s
                s.commit()
            except BaseException:
                s.rollback()
                raise

    def dispose(self) -> None:
        self.engine.dispose()
