"""Provenance rows (ARCHITECTURE.md §5.2): every AI or algorithmic row links to one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.storage.models_project import Provenance


@dataclass(frozen=True)
class ProvenanceInfo:
    kind: str
    algorithm_version: str | None = None
    prompt_version: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    input_keys: Sequence[str] = field(default_factory=tuple)
    config_hash: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def record(session: Session, info: ProvenanceInfo) -> int:
    row = Provenance(
        kind=info.kind,
        provider=info.provider,
        model=info.model,
        model_version=info.model_version,
        prompt_version=info.prompt_version,
        algorithm_version=info.algorithm_version,
        input_keys=list(info.input_keys),
        config_hash=info.config_hash,
        tokens_in=info.tokens_in,
        tokens_out=info.tokens_out,
        cost_usd=info.cost_usd,
        created_at=now_iso(),
    )
    session.add(row)
    session.flush()
    return row.id
