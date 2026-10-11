"""Opening databases from several threads at once (M3.4: the webview's first requests
opened one project together and Alembic's process-global context broke)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mosaic.storage.db import Database


def test_parallel_opens_migrate_cleanly(tmp_path: Path) -> None:
    def open_one(i: int) -> str:
        db = Database(tmp_path / f"p{i % 3}.db", "project")
        db.dispose()
        return "ok"

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(open_one, range(24))) == ["ok"] * 24


def test_a_database_at_head_skips_the_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening a project at the newest schema runs no migration (ADR 0064): that check
    (Alembic plus a foreign-key scan) cost most of a library request on big trips."""
    from mosaic.storage import db as dbmod

    path = tmp_path / "p.db"
    Database(path, "project").dispose()  # new: migrated to head
    calls: list[str] = []
    real = dbmod.command.upgrade
    monkeypatch.setattr(
        dbmod.command, "upgrade", lambda *a, **k: calls.append("upgrade") or real(*a, **k)
    )
    Database(path, "project").dispose()
    assert calls == [], "already at head"
    # A database behind head still upgrades.
    import sqlite3

    con = sqlite3.connect(path)
    con.execute("UPDATE alembic_version SET version_num = 'behind'")
    con.commit()
    con.close()
    engine = dbmod.make_engine(path, wal=True)
    try:
        assert not dbmod.at_head(engine, "project")
    finally:
        engine.dispose()
