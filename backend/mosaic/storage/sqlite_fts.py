"""Full-text search over a project's segments: SQLite FTS5 (ARCHITECTURE.md §12; all
SQLite-only SQL lives in ``storage/sqlite_*``).

One row per (segment, field): ``visual`` (descriptions), ``tags`` (subjects and issues)
and ``speech`` (transcript text). The table is rebuilt by the search index stage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

TABLE = "search_fts"
FIELDS = ("visual", "tags", "speech")
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class TextHit:
    segment_id: int
    field: str
    rank: float  # bm25: lower is better
    snippet: str


def ensure(session: Session) -> None:
    session.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING fts5("
            "segment_id UNINDEXED, field UNINDEXED, body, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )
    )


def replace_all(session: Session, rows: Iterable[tuple[int, str, str]]) -> int:
    """Replace the whole index with ``(segment id, field, body)`` rows."""
    ensure(session)
    session.execute(text(f"DELETE FROM {TABLE}"))
    n = 0
    batch: list[dict[str, object]] = []
    for sid, field, body in rows:
        if not body.strip():
            continue
        batch.append({"s": sid, "f": field, "b": body})
        n += 1
        if len(batch) >= 500:
            session.execute(text(f"INSERT INTO {TABLE} VALUES (:s, :f, :b)"), batch)
            batch = []
    if batch:
        session.execute(text(f"INSERT INTO {TABLE} VALUES (:s, :f, :b)"), batch)
    return n


def match_query(query: str) -> str | None:
    """A safe FTS5 query: the words of ``query``, each quoted (no FTS syntax from the
    user), any of them matching; the ranking prefers rows with more of them."""
    words = [w for w in _WORD.findall(query.lower()) if len(w) > 1]
    if not words:
        return None
    return " OR ".join(f'"{w}"*' for w in dict.fromkeys(words))


def exists(session: Session) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :t"), {"t": TABLE}
        ).first()
        is not None
    )


def search(session: Session, query: str, fields: tuple[str, ...], limit: int) -> list[TextHit]:
    """Read-only: no index yet means no hits (only the index stage creates the table)."""
    q = match_query(query)
    if q is None or not exists(session):
        return []
    placeholders = ", ".join(f":f{i}" for i in range(len(fields)))
    rows = session.execute(
        text(
            f"SELECT segment_id, field, bm25({TABLE}) AS r, "
            f"snippet({TABLE}, 2, '[', ']', '…', 12) "
            f"FROM {TABLE} WHERE {TABLE} MATCH :q AND field IN ({placeholders}) "
            "ORDER BY r LIMIT :n"
        ),
        {"q": q, "n": limit, **{f"f{i}": f for i, f in enumerate(fields)}},
    )
    return [TextHit(int(r[0]), str(r[1]), float(r[2]), str(r[3])) for r in rows]
