"""M0 acceptance 4 (schema half): no float time columns in either migrated DB.

The JSON half runs over real DB rows and the edit JSON export in the M0 acceptance suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from mosaic.core.timecheck import find_float_times, is_time_like
from mosaic.storage.db import Database
from mosaic.storage.models_control import ControlBase
from mosaic.storage.models_project import ProjectBase

TREES = [("control", ControlBase), ("project", ProjectBase)]


@pytest.mark.parametrize(("tree", "base"), TREES)
def test_migrated_schema_has_no_real_time_columns(tmp_path: Path, tree: str, base: type) -> None:
    db = Database(tmp_path / f"{tree}.db", tree)  # type: ignore[arg-type]
    offenders = []
    with db.engine.connect() as conn:
        for table in inspect(conn).get_table_names():
            for col in conn.execute(text(f"PRAGMA table_info('{table}')")).mappings():
                affinity = str(col["type"]).upper()
                is_real = any(t in affinity for t in ("REAL", "FLOA", "DOUB", "NUMERIC"))
                if is_real and is_time_like(col["name"]):
                    offenders.append(f"{table}.{col['name']}")
    db.dispose()
    assert not offenders, offenders


@pytest.mark.parametrize(("tree", "base"), TREES)
def test_migrations_match_models(tmp_path: Path, tree: str, base: type) -> None:
    db = Database(tmp_path / f"{tree}.db", tree)  # type: ignore[arg-type]
    with db.engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "include_name": lambda name, type_, _p: (
                    not (type_ == "table" and str(name).startswith("vec_"))
                )
            },
        )
        diff = compare_metadata(ctx, base.metadata)
    db.dispose()
    assert diff == [], diff


def test_detector() -> None:
    assert is_time_like("start_time")
    assert is_time_like("source_in")
    assert is_time_like("duration")
    assert is_time_like("trim_head")
    assert not is_time_like("cost_usd")
    assert not is_time_like("lufs_integrated")
    assert not is_time_like("sharpness")
    doc = {
        "range": {"start": {"ticks": 1, "tb": "1/90000"}},
        "duration": "828.36",
        "events": [{"timeline_in": 1.5, "gain_db": -12.0}],
        "cost_usd": 0.12,
    }
    assert find_float_times(doc) == ["$.duration", "$.events[0].timeline_in"]
