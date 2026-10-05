"""Trip context (PRODUCT.md §3): optional facts the owner gives about the trip.

It improves summaries, story beats, titles and chronology; every prompt works without it.
Names of places and people may appear in titles and captions only when they come from
here, metadata or explicit user input (invariant 16). Changing it re-runs summaries and
edits, never vision (the vision prompt does not contain it).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.storage.models_project import TripContextRow


def _zone(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {v!r} (use an IANA name like Europe/Paris)") from None
    return v


class Day(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="ISO date, YYYY-MM-DD")
    place: str = Field(default="", max_length=200)
    timezone: str | None = None
    notes: str = Field(default="", max_length=500)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return date.fromisoformat(v).isoformat()  # stored canonical: YYYY-MM-DD

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _zone(v)


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)


class TripContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip_name: str = Field(default="", max_length=120)
    home_timezone: str | None = None
    days: list[Day] = Field(default_factory=list, max_length=366)
    people: list[Person] = Field(default_factory=list, max_length=50)
    must_include: list[Annotated[str, Field(max_length=300)]] = Field(
        default_factory=list, max_length=50
    )
    avoid: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=50)
    free_notes: str = Field(default="", max_length=4000)

    @field_validator("home_timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _zone(v)

    def is_empty(self) -> bool:
        return self == TripContext()

    def digest(self) -> str:
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def prompt_text(self) -> str:
        """The context as prompt text, or "(none)". The source of any names the AI may use."""
        if self.is_empty():
            return "(none)"
        lines = []
        if self.trip_name:
            lines.append(f"Trip: {self.trip_name}")
        if self.free_notes:
            lines.append(f"Notes: {self.free_notes}")
        for d in self.days:
            bits = [d.date]
            if d.place:
                bits.append(d.place)
            if d.notes:
                bits.append(d.notes)
            lines.append("Day " + " — ".join(bits))
        for p in self.people:
            lines.append(f"Person: {p.label}" + (f" ({p.description})" if p.description else ""))
        if self.must_include:
            lines.append("Must include: " + "; ".join(self.must_include))
        if self.avoid:
            lines.append("Avoid: " + "; ".join(self.avoid))
        return "\n".join(lines)


def load(session: Session) -> TripContext:
    row = session.scalar(select(TripContextRow).where(TripContextRow.id == 1))
    return TripContext.model_validate(row.data) if row else TripContext()


Source = Literal["user", "ai_parsed"]


def revision(session: Session) -> int:
    row = session.get(TripContextRow, 1)
    return row.revision if row else 0


def save(session: Session, ctx: TripContext, source: Source) -> int:
    """Store the confirmed context (``source``: user|ai_parsed); returns its revision."""
    row = session.get(TripContextRow, 1)
    data: dict[str, Any] = ctx.model_dump(mode="json")
    if row is None:
        row = TripContextRow(id=1, data=data, revision=1, source=source, updated_at=now_iso())
        session.add(row)
    else:
        row.data, row.source, row.updated_at = data, source, now_iso()
        row.revision += 1
    session.flush()
    return row.revision
