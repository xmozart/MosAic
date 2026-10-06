"""Project and control DB migrations over existing data (the M1 eval found that a table
rebuild failed on a real M0 project: foreign keys referenced the rebuilt table)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

from mosaic.storage.db import Tree, alembic_config, migrate
from mosaic.storage.sqlite_engine import (
    MigrationIntegrityError,
    make_engine,
    migration_transaction,
)

# The schema each milestone shipped: projects made then must open now.
OLD_HEADS = {
    "project": ["d341738442d4", "a7c3e2d91f04", "c92d4e1f7a38"],  # M0 end, M1.4, M1.9b
    "control": ["faf1ebf5cb97"],
}


def _filler(decl: str) -> object:
    t = decl.upper()
    if "INT" in t or "BOOL" in t:
        return 1
    if "FLOAT" in t or "REAL" in t or "NUMERIC" in t:
        return 1.0
    if "JSON" in t:
        return "[]"
    return "x"


def _populate(db: Path) -> dict[str, int]:
    """One row in every table, parents first, every reference pointing at row 1."""
    con = sqlite3.connect(db)
    tables = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' AND sql NOT LIKE "
            "'CREATE VIRTUAL%'"
        )
    ]
    parents = {
        t: {r[2] for r in con.execute(f"PRAGMA foreign_key_list('{t}')") if r[2] != t}
        for t in tables
    }
    done: list[str] = []
    while len(done) < len(tables):
        ready = [t for t in tables if t not in done and parents[t] <= set(done)]
        assert ready, f"reference cycle among {set(tables) - set(done)}"
        done += sorted(ready)
    con.execute("PRAGMA foreign_keys=ON")
    inserted: dict[tuple[str, str], object] = {}
    for t in done:
        refs = {r[3]: (r[2], r[4]) for r in con.execute(f"PRAGMA foreign_key_list('{t}')")}
        row: dict[str, object] = {}
        for _cid, name, decl, notnull, _default, pk in con.execute(f"PRAGMA table_info('{t}')"):
            if name in refs and refs[name][0] != t:
                row[name] = inserted[refs[name]]
            elif notnull or pk:
                row[name] = _filler(decl)
        marks = ", ".join("?" for _ in row)
        cols = ", ".join(f'"{c}"' for c in row)
        con.execute(f'INSERT INTO "{t}" ({cols}) VALUES ({marks})', list(row.values()))
        rowid = con.execute(f'SELECT max(rowid) FROM "{t}"').fetchone()[0]
        for name, value in row.items():
            inserted[(t, name)] = value
        inserted.setdefault((t, "id"), rowid)
    con.commit()
    counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in done}
    con.close()
    return counts


@pytest.mark.parametrize(
    ("tree", "rev"), [(tree, rev) for tree, revs in OLD_HEADS.items() for rev in revs]
)
def test_populated_db_upgrades_to_head(tmp_path: Path, tree: Tree, rev: str) -> None:
    db = tmp_path / f"{tree}.db"
    cfg = alembic_config(tree, f"sqlite:///{db}")
    command.upgrade(cfg, rev)
    before = _populate(db)
    engine = make_engine(db, wal=False)  # the product's engine: foreign keys on
    migrate(engine, tree)
    engine.dispose()
    con = sqlite3.connect(db)
    after = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in before}
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()
    assert after == before, "every row survives the rebuilds"


def test_a_failed_migration_leaves_no_tables_behind(tmp_path: Path) -> None:
    """DDL is inside the transaction: the driver must not commit a CREATE on its own."""
    engine = make_engine(tmp_path / "t.db", wal=False)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE kept (id INTEGER PRIMARY KEY)"))
        conn.commit()

    def failing_upgrade() -> None:
        with engine.connect() as conn, migration_transaction(conn):
            conn.execute(text("CREATE TABLE leaked (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO kept (id) VALUES (1)"))
            conn.execute(text("DROP TABLE kept"))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        failing_upgrade()
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master"))}
        assert "leaked" not in names
        assert "kept" in names
        assert conn.execute(text("SELECT count(*) FROM kept")).scalar() == 0
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1, "back on"
    engine.dispose()


def test_broken_references_roll_the_migration_back(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "t.db", wal=False)

    def bad_upgrade() -> None:
        with engine.connect() as conn, migration_transaction(conn):
            conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
            conn.execute(
                text("CREATE TABLE child (id INTEGER PRIMARY KEY, p INTEGER REFERENCES parent(id))")
            )
            conn.execute(text("INSERT INTO child (id, p) VALUES (1, 42)"))  # no parent 42

    with pytest.raises(MigrationIntegrityError):
        bad_upgrade()
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master"))}
        assert not names & {"parent", "child"}
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    engine.dispose()
