"""sqlite-vec vector indexes (ARCHITECTURE.md §12). SQLite-only SQL lives here.

One ``vec0`` virtual table per (owner kind, model, dimension), so a search for segments
never returns samples; rows use the ``embedding.id`` as rowid,
so the index is a pure mirror of the ``embedding`` table and can be rebuilt from it.
"""

from __future__ import annotations

import re

import numpy as np
import numpy.typing as npt
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mosaic.core.keys import digest
from mosaic.storage.models_project import Embedding

PREFIX = "vec_"


def index_name(model: str, dim: int, kind: str) -> str:
    if kind not in ("sample", "segment"):
        raise ValueError(f"unknown embedding owner kind {kind!r}")
    name = f"{PREFIX}{kind}_{digest(model, 12)}_{dim}"
    if not re.fullmatch(r"vec_(sample|segment)_[0-9a-f]{12}_\d+", name):
        raise ValueError(name)
    return name


def ensure_index(session: Session, model: str, dim: int, kind: str) -> str:
    name = index_name(model, dim, kind)
    session.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0("
            f"embedding float[{dim}] distance_metric=cosine)"
        )
    )
    return name


def upsert(session: Session, name: str, rowid: int, vector: npt.NDArray[np.float32]) -> None:
    session.execute(text(f"DELETE FROM {name} WHERE rowid = :r"), {"r": rowid})
    session.execute(
        text(f"INSERT INTO {name}(rowid, embedding) VALUES (:r, :v)"),
        {"r": rowid, "v": vector.astype(np.float32).tobytes()},
    )


def delete(session: Session, name: str, rowids: list[int]) -> None:
    for r in rowids:
        session.execute(text(f"DELETE FROM {name} WHERE rowid = :r"), {"r": r})


def knn(
    session: Session, name: str, vector: npt.NDArray[np.float32], k: int
) -> list[tuple[int, float]]:
    """``(rowid, cosine distance)`` of the ``k`` nearest vectors."""
    rows = session.execute(
        text(
            f"SELECT rowid, distance FROM {name} WHERE embedding MATCH :v AND k = :k "
            "ORDER BY distance"
        ),
        {"v": vector.astype(np.float32).tobytes(), "k": k},
    )
    return [(int(r), float(d)) for r, d in rows]


def delete_embeddings(session: Session, kind: str, owner_ids: list[int]) -> int:
    """Delete ``embedding`` rows of ``kind`` for ``owner_ids`` and their index mirrors."""
    if not owner_ids:
        return 0
    rows = list(
        session.execute(
            select(Embedding.id, Embedding.model, Embedding.dim).where(
                Embedding.owner_kind == kind, Embedding.owner_id.in_(owner_ids)
            )
        )
    )
    by_index: dict[str, list[int]] = {}
    for emb_id, model, dim in rows:
        by_index.setdefault(index_name(model, dim, kind), []).append(emb_id)
    for name, ids in by_index.items():
        exists = session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :n"), {"n": name}
        ).first()
        if exists:
            delete(session, name, ids)
    session.execute(sa_delete(Embedding).where(Embedding.id.in_([r[0] for r in rows])))
    return len(rows)
