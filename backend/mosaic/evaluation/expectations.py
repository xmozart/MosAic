"""Trip expectations (EVALUATION.md §1): must-include moments and must-exclude material.

Expectations live in the repo (``tests/evaluation/corpus/<trip>/expectations.yaml``), never
in the trip folder. When a trip has none, a **draft** is generated from the analysis and
marked ``draft: true``: must-exclude from rule/AI REJECTs of accidental, pocket and
obstructed material; must-include from the most interesting, well-composed moments. Draft
metrics are reported but never block until the owner confirms them at gate G6.

Ranges are stored as source files with integer ticks (invariant 3), plus a display string.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.time import format_display, parse_rational
from mosaic.library.dispositions import effective
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    MediaFile,
    Segment,
    VisualObservation,
)

EXCLUDE_CODES = {
    "accidental_recording",
    "accidental",
    "pocket_or_covered",
    "obstructed",
    "black_frames",
}
INCLUDE_LIMIT = 8


@dataclass(frozen=True)
class Moment:
    file: str
    asset_id: int
    start: int  # asset logical ticks
    end: int
    tb: str
    note: str

    def overlaps(self, asset_id: int, a: int, b: int) -> bool:
        return asset_id == self.asset_id and a < self.end and b > self.start


def _first_file(s: Session, asset_id: int) -> str:
    return str(
        s.scalar(
            select(MediaFile.rel_path)
            .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
            .where(AssetFile.asset_id == asset_id)
            .order_by(AssetFile.order)
            .limit(1)
        )
        or "?"
    )


def _entry(s: Session, seg: Segment, tb: str, note: str) -> dict[str, Any]:
    r = parse_rational(tb)
    a = Fraction(seg.usable_start_ticks) * r
    b = Fraction(seg.usable_end_ticks) * r
    return {
        "file": _first_file(s, seg.asset_id),
        "asset": f"ast_{seg.asset_id:04d}",
        "range": {
            "start": {"ticks": seg.usable_start_ticks, "tb": tb},
            "end": {"ticks": seg.usable_end_ticks, "tb": tb},
        },
        "display": f"{format_display(a)}–{format_display(b)}",
        "note": note,
    }


def draft(session: Session, trip: str) -> dict[str, Any]:
    exclude: list[dict[str, Any]] = []
    include: list[tuple[int, dict[str, Any]]] = []
    for asset in session.scalars(select(Asset).where(Asset.kind == "video").order_by(Asset.id)):
        if asset.tb is None:
            continue
        segs = list(session.scalars(select(Segment).where(Segment.asset_id == asset.id)))
        disp = effective(session, [g.id for g in segs])
        obs = {
            o.segment_id: o.data
            for o in session.scalars(
                select(VisualObservation).where(
                    VisualObservation.segment_id.in_([g.id for g in segs])
                )
            )
        }
        for g in segs:
            d = disp.get(g.id)
            codes = {r.get("code") for r in (d.reasons if d else [])}
            if d is not None and d.status == "REJECT" and codes & EXCLUDE_CODES:
                exclude.append(
                    _entry(session, g, asset.tb, ", ".join(sorted(codes & EXCLUDE_CODES)))
                )
                continue
            o = obs.get(g.id) or {}
            if d is not None and d.status == "REJECT":
                continue
            if o.get("interest") == "high" and o.get("composition") in ("good", "excellent"):
                score = 2 if o.get("composition") == "excellent" else 1
                include.append((score, _entry(session, g, asset.tb, o.get("description", ""))))
    include.sort(key=lambda se: -se[0])
    return {
        "trip": trip,
        "draft": True,
        "note": "Generated from analysis; confirm or edit at gate G6 (EVALUATION.md §1).",
        "must_include": [e for _, e in include[:INCLUDE_LIMIT]],
        "must_exclude": exclude,
    }


def load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return data


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))


def file_assets(session: Session) -> dict[str, int]:
    """Relative file path → asset id in this project (expectations name files)."""
    return {
        str(path): int(aid)
        for path, aid in session.execute(select(MediaFile.rel_path, MediaFile.asset_id))
        if aid is not None
    }


def moments(entries: list[dict[str, Any]], files: dict[str, int] | None = None) -> list[Moment]:
    """The file name is authoritative: it is resolved to this project's asset, so a
    re-initialised project (new asset ids) is still scored correctly."""
    out = []
    for e in entries:
        rng = e["range"]
        name = str(e.get("file", "?"))
        asset = (files or {}).get(name)
        out.append(
            Moment(
                file=name,
                asset_id=asset if asset is not None else int(str(e["asset"]).removeprefix("ast_")),
                start=int(rng["start"]["ticks"]),
                end=int(rng["end"]["ticks"]),
                tb=str(rng["start"]["tb"]),
                note=str(e.get("note", "")),
            )
        )
    return out


def _overlaps(m: Moment, event: dict[str, Any]) -> bool:
    """Overlap in exact time: the moment's ticks are rescaled to the event's time base."""
    if int(event["asset_id"][4:]) != m.asset_id:
        return False
    etb = parse_rational(event["source_in"]["tb"])
    mtb = parse_rational(m.tb)
    a = Fraction(event["source_in"]["ticks"]) * etb
    b = Fraction(event["source_out"]["ticks"]) * etb
    return a < Fraction(m.end) * mtb and b > Fraction(m.start) * mtb


def score(
    expect: dict[str, Any], events: list[dict[str, Any]], files: dict[str, int] | None = None
) -> dict[str, Any]:
    """Must-include recall and must-exclude violations of an edit's events."""
    inc = moments(expect.get("must_include", []), files)
    exc = moments(expect.get("must_exclude", []), files)
    hit = [m for m in inc if any(_overlaps(m, e) for e in events)]
    bad = [m for m in exc if any(_overlaps(m, e) for e in events)]
    return {
        "draft": bool(expect.get("draft", True)),
        "must_include_total": len(inc),
        "must_include_hit": len(hit),
        "must_include_recall": None if not inc else round(len(hit) / len(inc), 3),
        "must_exclude_total": len(exc),
        "must_exclude_violations": len(bad),
        "violations": [f"{m.file} {m.note}" for m in bad],
    }
