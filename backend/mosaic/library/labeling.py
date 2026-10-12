""" "Help me label" (S24; PRODUCT.md §3: "after L2, the app may ask up to 5 targeted,
skippable questions"; ADR 0085).

Questions come from what analysis already knows, with no new AI call and nothing about
faces: days whose place the itinerary lacks, clips the vision observations say show one
or a few people, close together on one day, and a day full of high-interest moments that
the owner has not described. Answers become only trip-context records (a day's place or
notes, a person's label) and ``person_link`` rows (a label the owner typed, and a clip);
no face, embedding or other biometric data is ever stored.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.editing.retrieval import first_capture_date, trip_day
from mosaic.editing.titles import MONTHS, WEEKDAYS
from mosaic.library.context import Day, Person, TripContext
from mosaic.library.context import load as load_context
from mosaic.library.context import save as save_context
from mosaic.storage.models_project import (
    Asset,
    LabelingQuestion,
    PersonLink,
    SampleFrame,
    Segment,
    VisualObservation,
)
from mosaic.storage.projects import Project

MAX_OPEN = 5
MAX_PER_KIND = {"place": 2, "same_person": 2, "event": 1}
NEAR = timedelta(minutes=30)  # clips this close on one day may show the same person
FEW_PEOPLE = ("one", "few")


class AnswerError(ValueError):
    """An answer that does not fit its question; the message is for the owner."""


Choice = Literal["yes", "no", "not_sure"]


def _date_text(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def _asset_days(s: Session, first: date | None) -> dict[int, tuple[int, datetime | None]]:
    """Each video's trip day and capture time as local wall-clock time (no zone: phone
    times carry an offset, camera-local ones none; days compare dates, as ``trip_day``
    does). Day 0: unknown."""
    out: dict[int, tuple[int, datetime | None]] = {}
    q = select(Asset.id, Asset.capture_time).where(Asset.kind == "video", Asset.status == "ok")
    for aid, ct in s.execute(q.execution_options(yield_per=1000)):
        when = None
        if ct:
            try:
                when = datetime.fromisoformat(ct.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                when = None
        out[aid] = (max(0, trip_day(ct, Fraction(0), first)) if when else 0, when)
    return out


def _samples(s: Session, asset_ids: list[int]) -> list[int]:
    """One kept frame per clip (the first), to show with the question."""
    rows = dict(
        s.execute(
            select(SampleFrame.asset_id, func.min(SampleFrame.id))
            .where(
                SampleFrame.asset_id.in_(asset_ids),
                SampleFrame.kept.is_(True),
                SampleFrame.image_key.is_not(None),
            )
            .group_by(SampleFrame.asset_id)
        ).all()
    )
    return [rows[a] for a in asset_ids if a in rows]


def _near(a: datetime | None, b: datetime | None) -> bool:
    """Two clips close enough in time (both known) to ask whether they show one person."""
    return a is not None and b is not None and abs(b - a) <= NEAR


def _candidates(s: Session, trip: TripContext) -> list[dict[str, Any]]:
    """Every question the library could ask now, best first within each kind."""
    first = first_capture_date(s)
    days = _asset_days(s, first)
    by_day: dict[int, list[int]] = defaultdict(list)
    for aid, (day, _) in sorted(days.items(), key=lambda kv: (kv[1][1] or datetime.min, kv[0])):
        if day:
            by_day[day].append(aid)
    places = {d.date: d.place for d in trip.days}
    out: list[dict[str, Any]] = []
    if first is not None:
        for day in sorted(by_day):
            when = first + timedelta(days=day - 1)
            if places.get(when.isoformat()):
                continue
            out.append(
                {
                    "kind": "place",
                    "subject": f"place:{when.isoformat()}",
                    "day": day,
                    "assets": by_day[day][:4],
                    "text": f"Where were you on Day {day} ({_date_text(when)})?",
                }
            )
    # Clips the observations say show one or a few people, close in time on one day.
    obs = defaultdict(set)
    q = (
        select(Segment.asset_id, VisualObservation.data)
        .join(VisualObservation, VisualObservation.segment_id == Segment.id)
        .execution_options(yield_per=1000)
    )
    for aid, data in s.execute(q):
        obs[aid].add((data or {}).get("people"))
        if (data or {}).get("interest") == "high":
            obs[aid].add("interest:high")
    for day in sorted(by_day):
        people = [a for a in by_day[day] if obs[a] & set(FEW_PEOPLE)]
        group: list[int] = []
        for a in people:
            if group and not _near(days[group[-1]][1], days[a][1]):
                if len(group) >= 2:
                    break
                group = []
            group.append(a)
            if len(group) == 3:
                break
        if len(group) >= 2:
            out.append(
                {
                    "kind": "same_person",
                    "subject": "same_person:" + ",".join(map(str, sorted(group))),
                    "day": day,
                    "assets": group,
                    "text": "Is this the same person in these clips?",
                }
            )
    noted = {d.date for d in trip.days if d.notes.strip()}
    busiest = sorted(
        by_day,
        key=lambda d: (-sum("interest:high" in obs[a] for a in by_day[d]), d),
    )
    for day in busiest:
        highs = [a for a in by_day[day] if "interest:high" in obs[a]]
        on = first + timedelta(days=day - 1) if first else None
        if len(highs) < 2 or on is None or on.isoformat() in noted:
            continue
        out.append(
            {
                "kind": "event",
                "subject": f"event:{on.isoformat()}",
                "day": day,
                "assets": highs[:4],
                "text": f"What was happening on Day {day} ({_date_text(on)})?",
            }
        )
    return out


def questions(project: Project) -> list[LabelingQuestion]:
    """The open questions (at most five), asking new ones when there is room: never one
    already answered or skipped, nor one the trip context now answers."""
    with project.write() as s:
        _close_answered(s)
    with project.db.session() as s:
        trip = load_context(s)
        asked = set(s.scalars(select(LabelingQuestion.subject)))
        open_now = list(
            s.scalars(select(LabelingQuestion).where(LabelingQuestion.status == "open"))
        )
        room = MAX_OPEN - len(open_now)
        fresh: list[dict[str, Any]] = []
        per_kind: dict[str, int] = defaultdict(int)
        for q in open_now:
            per_kind[q.kind] += 1
        if room > 0:
            for c in _candidates(s, trip):
                if c["subject"] in asked or per_kind[c["kind"]] >= MAX_PER_KIND[c["kind"]]:
                    continue
                c["samples"] = _samples(s, c["assets"])
                fresh.append(c)
                per_kind[c["kind"]] += 1
                if len(fresh) == room:
                    break
    if fresh:
        with project.write() as s:
            # Another request may have asked the same question since it was read.
            taken = set(s.scalars(select(LabelingQuestion.subject)))
            for c in fresh:
                if c["subject"] in taken:
                    continue
                s.add(
                    LabelingQuestion(
                        uid=new_ulid(),
                        kind=c["kind"],
                        subject=c["subject"],
                        day=c["day"],
                        asset_ids=c["assets"],
                        sample_ids=c["samples"],
                        text=c["text"],
                        status="open",
                        answer=None,
                        created_at=now_iso(),
                        answered_at=None,
                    )
                )
    with project.db.session() as s:
        order = {"place": 0, "same_person": 1, "event": 2}
        rows = list(s.scalars(select(LabelingQuestion).where(LabelingQuestion.status == "open")))
        for r in rows:
            s.expunge(r)
    return sorted(rows, key=lambda q: (order[q.kind], q.id))


def _close_answered(s: Session) -> None:
    """Open place and event questions the owner has since answered in the trip context
    (S7) are closed: never ask what the context already says."""
    trip = load_context(s)
    places = {d.date for d in trip.days if d.place.strip()}
    notes = {d.date for d in trip.days if d.notes.strip()}
    for q in s.scalars(
        select(LabelingQuestion).where(
            LabelingQuestion.status == "open", LabelingQuestion.kind.in_(("place", "event"))
        )
    ):
        when = q.subject.split(":", 1)[1]
        if when in (places if q.kind == "place" else notes):
            q.status, q.answered_at = "answered", now_iso()
            q.answer = {"from": "trip_context"}


def as_json(q: LabelingQuestion, trip: TripContext | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "question_id": q.uid,
        "kind": q.kind,
        "day": q.day,
        "text": q.text,
        "asset_ids": q.asset_ids,
        "sample_ids": q.sample_ids,
        "status": q.status,
    }
    if q.kind == "same_person" and trip is not None:
        out["people"] = [p.label for p in trip.people]  # the name field's suggestions
    return out


def answer(
    project: Project,
    uid: str,
    *,
    skip: bool = False,
    choice: Choice | None = None,
    name: str | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    """Record the owner's answer: a day's place or notes in the trip context, or a person
    linked to the question's clips. ``skip``: never asked again, nothing recorded."""
    with project.write() as s:
        q = s.scalar(select(LabelingQuestion).where(LabelingQuestion.uid == uid))
        if q is None:
            raise LookupError("no such question")
        if q.status != "open":
            raise AnswerError("This question was answered already.")
        result: dict[str, Any] = {}
        if skip:
            q.status, q.answer = "skipped", None
        elif q.kind in ("place", "event"):
            words = " ".join((text or "").split())
            if not words:
                raise AnswerError("Type an answer, or skip the question.")
            trip = load_context(s)
            when = q.subject.split(":", 1)[1]
            days = {d.date: d for d in trip.days}
            day = days.get(when) or Day(date=when)
            if q.kind == "place":
                day = day.model_copy(update={"place": words[:200]})
            else:
                notes = f"{day.notes} {words}".strip() if day.notes else words
                day = day.model_copy(update={"notes": notes[:500]})
            days[when] = day
            trip = _valid(trip, days=sorted(days.values(), key=lambda d: d.date))
            result["context_revision"] = save_context(s, trip, "user")
            q.status, q.answer = "answered", {"text": words}
        else:  # same_person
            if choice is None:
                raise AnswerError("Choose Yes, No or Not sure.")
            linked: list[int] = []
            label = " ".join((name or "").split())
            if choice == "yes" and not label:
                raise AnswerError("Who is it? Type a name, or choose Not sure.")
            if choice == "yes":
                trip = load_context(s)
                known = {p.label.casefold(): p.label for p in trip.people}
                label = known.get(label.casefold(), label[:60])
                if label.casefold() not in known:  # a person the owner just named
                    trip = _valid(trip, people=[*trip.people, Person(label=label)])
                    result["context_revision"] = save_context(s, trip, "user")
                have = set(s.scalars(select(PersonLink.asset_id).where(PersonLink.label == label)))
                for aid in q.asset_ids:
                    if aid not in have:
                        s.add(
                            PersonLink(
                                label=label, asset_id=aid, question_id=q.id, created_at=now_iso()
                            )
                        )
                        linked.append(aid)
            q.status = "answered"
            q.answer = {"choice": choice, "name": label or None}
            result["linked"] = linked
        q.answered_at = now_iso()
        return {"question_id": q.uid, "status": q.status, **result}


def _valid(trip: TripContext, **change: Any) -> TripContext:
    """``trip`` with ``change``, validated as a whole (a stored context always loads)."""
    try:
        return TripContext.model_validate(
            trip.model_dump(mode="json")
            | {k: [x.model_dump(mode="json") for x in v] for k, v in change.items()}
        )
    except ValidationError:
        if "people" in change:
            raise AnswerError("The trip already lists as many people as it can.") from None
        raise AnswerError("The trip context can't take this answer.") from None


def links(s: Session, asset_id: int) -> list[str]:
    """The people the owner linked to a clip."""
    return list(
        s.scalars(
            select(PersonLink.label).where(PersonLink.asset_id == asset_id).order_by(PersonLink.id)
        )
    )
