"""Title cards in an edit (M4: "minimal title cards (opening, day cards, closing) in one
modern style"; ADR 0079).

What a card says comes only from the trip context and capture metadata (invariant 16):
the trip's name as the owner typed it, the dates the edit's footage was shot, and a day's
place from the itinerary. Never from the AI: the planner's working title stays in the
timeline's metadata and is never drawn.

- **Opening** (3 s): the trip's name over the dates, or the dates alone.
- **Day cards** (2 s): "Day N" over the itinerary's place for that date and the date, at
  the first shot of each day, when the edit follows the order things happened, covers at
  least two days and is at least a minute long.
- **Closing** (3 s): the trip's name, when there is one.

Cards take at most 15 % of the edit; day cards go first when they would not fit (all of
them: one day card alone tells nothing). A line the bundled fonts cannot draw is left
out, and a card with no line is not made.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from typing import Any, Literal

from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.editing.request import EditRequest
from mosaic.library.context import TripContext
from mosaic.media.titles import covered

CardKind = Literal["opening", "day", "closing"]
SECONDS: dict[str, Fraction] = {"opening": Fraction(3), "day": Fraction(2), "closing": Fraction(3)}
MIN_EDIT_S = 20  # shorter edits get no cards
MIN_DAYS_EDIT_S = 60  # day cards only from a minute up
MAX_SHARE = Fraction(15, 100)
DIP = Fraction(1, 2)  # seconds: a card fades in from and out to black (ADR 0066, 0078)


@dataclass(frozen=True)
class Card:
    kind: CardKind
    title: str
    subtitle: str
    frames: int
    day: int = 0

    def as_json(self) -> dict[str, Any]:
        return {"card": self.kind, "title": self.title, "subtitle": self.subtitle, "day": self.day}


@dataclass(frozen=True)
class Cards:
    """An edit's cards: the opening, the day cards before the first shot of their day
    (by the shot's index in the edit), and the closing."""

    opening: Card | None = None
    days: dict[int, Card] | None = None
    closing: Card | None = None

    @property
    def frames(self) -> int:
        cards = [self.opening, self.closing, *(self.days or {}).values()]
        return sum(c.frames for c in cards if c is not None)

    def before(self, index: int) -> list[Card]:
        """The cards that go before shot ``index`` (``len(shots)`` for the closing)."""
        out = []
        if index == 0 and self.opening:
            out.append(self.opening)
        if self.days and index in self.days:
            out.append(self.days[index])
        return out


def _frames(kind: str, rate: str) -> int:
    return round_fraction(SECONDS[kind] * parse_rational(rate), Rounding.NEAREST)


def _drawable(text: str) -> str:
    text = " ".join(text.split())
    return text if text and covered(text) else ""


# English names, never the process locale's: a card's text must not depend on where the
# server runs (its key and the fonts' coverage are checked on this text).
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _month(d: date) -> str:
    return MONTHS[d.month - 1]


def date_span(first: date, last: date) -> str:
    """'14 June 2026', '12 – 18 June 2026', '28 June – 3 July 2026' or across years."""
    if first == last:
        return f"{first.day} {_month(first)} {first.year}"
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day} – {last.day} {_month(last)} {last.year}"
    if first.year == last.year:
        return f"{first.day} {_month(first)} – {last.day} {_month(last)} {last.year}"
    return f"{first.day} {_month(first)} {first.year} – {last.day} {_month(last)} {last.year}"


def day_date(day1: date, day: int) -> date:
    return day1 + timedelta(days=day - 1)


def plan_cards(
    req: EditRequest,
    trip: TripContext,
    day1: date | None,
    days: list[int],
    rate: str,
    target: int,
) -> Cards:
    """The cards for an edit whose shots fall on trip ``days`` (in edit order; 0 when
    unknown), with trip day 1 on ``day1``."""
    if req.duration_s < MIN_EDIT_S:
        return Cards()
    known = sorted({d for d in days if d >= 1})
    span = date_span(day_date(day1, known[0]), day_date(day1, known[-1])) if day1 and known else ""
    name = _drawable(trip.trip_name)
    opening = None
    if name or span:
        opening = Card("opening", name or span, span if name else "", _frames("opening", rate))
    closing = Card("closing", name, "", _frames("closing", rate)) if name else None
    cards = Cards(opening, None, closing)
    day_cards = _day_cards(req, trip, day1, days, rate)
    with_days = Cards(opening, day_cards, closing)
    if day_cards and with_days.frames <= target * MAX_SHARE:
        return with_days
    return cards


def _day_cards(
    req: EditRequest, trip: TripContext, day1: date | None, days: list[int], rate: str
) -> dict[int, Card]:
    if req.chronology not in ("strict", "mostly") or req.duration_s < MIN_DAYS_EDIT_S or not day1:
        return {}
    places = {d.date: _drawable(d.place) for d in trip.days}
    out: dict[int, Card] = {}
    last = 0
    for i, day in enumerate(days):
        if day <= last:  # unknown, the same day, or back in time ("mostly"): no card
            continue
        last = day
        when = day_date(day1, day)
        label = f"{WEEKDAYS[when.weekday()]} {when.day} {_month(when)}"
        place = places.get(when.isoformat(), "")
        subtitle = f"{place} · {label}" if place else label
        out[i] = Card("day", f"Day {day}", subtitle, _frames("day", rate), day)
    return out if len(out) >= 2 else {}


def shot_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events that show footage: every event but the title cards."""
    return [e for e in events if e.get("kind") != "title"]


def dip_frames(card: Card, mode: str, rate: str) -> int:
    """A card's fade from and to black: none in "minimal" (cuts only, ADR 0066)."""
    if mode == "minimal":
        return 0
    return min(round_fraction(DIP * parse_rational(rate), Rounding.NEAREST), card.frames // 2)


def title_event(card: Card, event_id: str, pos: int, rate: str, mode: str) -> dict[str, Any]:
    """A card's timeline event: no source, silent, fading in and out."""
    dip = dip_frames(card, mode, rate)
    event: dict[str, Any] = {
        "event_id": event_id,
        "kind": "title",
        "asset_id": None,
        "segment_id": None,
        "title": card.as_json(),
        "timeline_in": {"frames": pos, "rate": rate},
        "timeline_out": {"frames": pos + card.frames, "rate": rate},
        "duration": {"frames": card.frames, "rate": rate},
        "audio": {
            "source_enabled": False,
            "gain_db": 0,
            "fade_in_frames": 0,
            "fade_out_frames": 0,
            "intent": "mute",
        },
        "transition_out": {"type": "dip", "frames": dip, "rate": rate} if dip else {"type": "cut"},
        "role": "title",
        "beat_id": None,
        "origin": {"card": card.kind, "locked": False},
    }
    if dip:
        event["transition_in"] = {"type": "dip", "frames": dip, "rate": rate}
    return event
