"""Opening databases from several threads at once (M3.4: the webview's first requests
opened one project together and Alembic's process-global context broke)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mosaic.storage.db import Database


def test_parallel_opens_migrate_cleanly(tmp_path: Path) -> None:
    def open_one(i: int) -> str:
        db = Database(tmp_path / f"p{i % 3}.db", "project")
        db.dispose()
        return "ok"

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(open_one, range(24))) == ["ok"] * 24
