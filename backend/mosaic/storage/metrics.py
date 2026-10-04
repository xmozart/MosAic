"""Set-based metric normalization (ARCHITECTURE.md §5.3).

Uses standard SQL window functions and ``UPDATE … FROM`` (SQLite ≥ 3.33, PostgreSQL), so
it runs in one statement whatever the project size (invariant 13).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

_SQL = """
UPDATE tech_metric
SET percentile = r.p
FROM (
    SELECT id,
           CASE WHEN COUNT(*) OVER (PARTITION BY name) = 1 THEN 0.5
                ELSE PERCENT_RANK() OVER (PARTITION BY name ORDER BY value) END AS p
    FROM tech_metric
    WHERE name NOT IN :excluded
) AS r
WHERE tech_metric.id = r.id
"""


def normalize_percentiles(session: Session, exclude: Sequence[str] = ()) -> int:
    """Set ``percentile`` for every metric row; tied values share a percentile."""
    stmt = text(_SQL).bindparams(bindparam("excluded", expanding=True))
    result = session.execute(stmt, {"excluded": list(exclude) or ["__none__"]})
    return int(result.rowcount)  # type: ignore[attr-defined]
