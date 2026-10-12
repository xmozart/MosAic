"""Title cards (ADR 0079): which cards an edit gets, what they say (only the trip context
and capture dates), how they sit in the timeline, and how they look."""

from __future__ import annotations

from datetime import date

import numpy as np

from mosaic.editing import critic, refiner
from mosaic.editing.request import EditRequest
from mosaic.editing.resolve import _after_cards
from mosaic.editing.titles import Card, Cards, date_span, plan_cards, shot_events, title_event
from mosaic.library.context import Day, TripContext
from mosaic.media.titles import card_image, covered
from tests.unit.test_editing import RATE, cand
from tests.unit.test_jl_cuts import _cut

DAY1 = date(2026, 6, 12)
TRIP = TripContext(
    trip_name="Iceland 2026",
    days=[Day(date="2026-06-13", place="Reykjavík"), Day(date="2026-06-14", place="ירושלים")],
)


def _req(seconds: int = 180, chronology: str = "strict") -> EditRequest:
    return EditRequest(duration_s=seconds, chronology=chronology)


def test_the_opening_names_the_trip_over_its_dates_and_the_closing_names_it_again() -> None:
    cards = plan_cards(_req(30), TRIP, DAY1, [1, 1, 3], RATE, 899)
    assert cards.opening == Card("opening", "Iceland 2026", "12 – 14 June 2026", 90)
    assert cards.closing == Card("closing", "Iceland 2026", "", 90)
    assert not cards.days, "a 30 s edit gets no day cards"
    plain = plan_cards(_req(30), TripContext(), DAY1, [1, 3], RATE, 899)
    assert plain.opening == Card("opening", "12 – 14 June 2026", "", 90)
    assert plain.closing is None, "nothing to close with but the dates again"
    assert plan_cards(_req(30), TripContext(), None, [0, 0], RATE, 899) == Cards()
    assert plan_cards(_req(15), TRIP, DAY1, [1], RATE, 449) == Cards(), "too short for cards"


def test_day_cards_follow_the_days_with_places_only_from_the_itinerary() -> None:
    cards = plan_cards(_req(), TRIP, DAY1, [1, 1, 2, 2, 3, 0, 2], RATE, 5395)
    assert cards.days is not None
    assert sorted(cards.days) == [0, 2, 4], "the first shot of each day, in order"
    assert cards.days[0] == Card("day", "Day 1", "Friday 12 June", 60, 1)
    assert cards.days[2].subtitle == "Reykjavík · Saturday 13 June"
    assert cards.days[4].subtitle == "Sunday 14 June", "a place the fonts can't draw is left out"
    assert [c.kind for c in cards.before(0)] == ["opening", "day"]
    # Thematic order, a single day or a short edit: no day cards.
    assert not plan_cards(_req(chronology="thematic"), TRIP, DAY1, [1, 2], RATE, 5395).days
    assert not plan_cards(_req(), TRIP, DAY1, [2, 2, 2], RATE, 5395).days
    assert not plan_cards(_req(45), TRIP, DAY1, [1, 2], RATE, 1348).days


def test_cards_take_at_most_15_percent_of_the_edit() -> None:
    many = list(range(1, 13))
    cards = plan_cards(_req(60), TRIP, DAY1, many, RATE, 1798)
    assert not cards.days, "twelve day cards would take 24 s of a minute"
    assert cards.frames == 180
    assert plan_cards(_req(600), TRIP, DAY1, many, RATE, 17982).days


def test_names_only_from_what_the_owner_typed() -> None:
    hebrew = TripContext(trip_name="טיול לאיסלנד")
    cards = plan_cards(_req(30), hebrew, DAY1, [1], RATE, 899)
    assert cards.opening == Card("opening", "12 June 2026", "", 90)
    assert cards.closing is None
    assert covered("Kraków · Đà Nẵng · Москва")
    assert not covered("東京")


def test_date_spans() -> None:
    assert date_span(date(2026, 6, 12), date(2026, 6, 12)) == "12 June 2026"
    assert date_span(date(2026, 6, 28), date(2026, 7, 3)) == "28 June – 3 July 2026"
    assert date_span(date(2026, 12, 30), date(2027, 1, 2)) == "30 December 2026 – 2 January 2027"


def _shots(days: list[int]) -> list[refiner.Cut]:
    cuts = []
    for i, day in enumerate(days):
        c = cand(i + 1, asset=i + 1, length_s=20, day=day)
        cuts.append(_cut(c, 4, 150, beat="b1"))
    return cuts


def test_cards_sit_between_the_shots_and_take_no_transitions() -> None:
    cuts = _shots([1, 1, 2])
    cards = plan_cards(_req(), TRIP, DAY1, [c.shot.cand.day for c in cuts], RATE, 5395)
    breaks = frozenset([0, 2, 3])
    refiner.choose_transitions(cuts, "dissolves", RATE, breaks)
    assert cuts[0].dip_in == 0, "the opening card fades in, not the first shot"
    assert cuts[-1].dip_out == 0
    assert cuts[1].dissolve == 0, "never a dissolve into a card"
    events = refiner.events(cuts, RATE, cards, "dissolves")
    kinds = [e["kind"] for e in events]
    assert kinds == ["title", "title", "video", "video", "title", "video", "title"]
    assert [e["event_id"] for e in events] == [f"evt_{i:04d}" for i in range(1, 8)]
    pos = 0
    for e in events:
        assert e["timeline_in"]["frames"] == pos
        pos = e["timeline_out"]["frames"]
    assert pos == 3 * 150 + cards.frames
    assert len(shot_events(events)) == 3
    card = events[0]
    assert card["title"] == {
        "card": "opening",
        "title": "Iceland 2026",
        "subtitle": "12 – 13 June 2026",
        "day": 0,
    }
    assert card["transition_in"]["frames"] == card["transition_out"]["frames"] == 15
    assert card["audio"]["source_enabled"] is False
    minimal = title_event(cards.opening, "evt_0001", 0, RATE, "minimal")  # type: ignore[arg-type]
    assert minimal["transition_out"] == {"type": "cut"}
    assert "transition_in" not in minimal


def test_findings_move_past_the_cards_before_them() -> None:
    cuts = _shots([1, 2])
    cards = Cards(Card("opening", "T", "", 90), {1: Card("day", "Day 2", "", 60, 2)}, None)
    findings = [
        critic.Finding("a", "warning", 0, "first shot"),
        critic.Finding("b", "warning", 150, "second shot"),
        critic.Finding("c", "warning", 200, "inside the second"),
    ]
    assert [f.frame for f in _after_cards(findings, cuts, cards)] == [90, 300, 350]


def test_a_card_is_light_text_on_a_dark_ground_at_the_outputs_size() -> None:
    img = card_image("Iceland 2026", "12 – 18 June 2026", 1280, 720)
    assert img.size == (1280, 720)
    px = np.asarray(img.convert("L"))
    assert px[:100].max() < 20, "nothing near the top"
    middle = px[300:420, 300:980]
    assert middle.max() > 200, "the title is drawn in the middle"
    tall = np.asarray(card_image("Day 3", "", 1080, 1920).convert("L"))
    rows = np.where(tall.max(axis=1) > 200)[0]
    assert 860 < rows.mean() < 1060, "centred on a vertical frame"
