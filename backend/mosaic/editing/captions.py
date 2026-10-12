"""SRT captions from the transcript (M4 exports; ADR 0084).

Captions follow what is heard: for every event whose sound is on, the transcript words
inside its heard window (its own J- or L-cut window when split, ADR 0077) are placed on
the timeline. Words are grouped into cues of at most two lines of 42 characters and
7 seconds, closed at sentence ends and at pauses. Times are exact fractions until they
are written as whole milliseconds (invariant 3).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.time import parse_rational
from mosaic.editing.titles import shot_events
from mosaic.render.plan import audio_span
from mosaic.storage.models_project import TranscriptWord

LINE = 42  # characters per line
MAX_CUE = Fraction(7)  # seconds
PAUSE = Fraction(7, 10)  # a gap this long between words starts a new cue
MIN_CUE = Fraction(1)  # a short cue is held this long, if the next one allows


@dataclass
class Word:
    start: Fraction  # timeline seconds
    end: Fraction
    text: str


def heard_words(s: Session, timeline: dict[str, Any]) -> Iterator[Word]:
    """Every heard word in timeline order (one event's words at a time, invariant 13)."""
    rate = parse_rational(timeline["rate"])
    for e in shot_events(timeline["tracks"][0]["events"]):
        audio = e.get("audio") or {}
        if e.get("kind") != "video" or not audio.get("source_enabled"):
            continue
        src_in, src_out, _ = audio_span(e)  # its heard window (ADR 0077)
        a, b = int(src_in["ticks"]), int(src_out["ticks"])
        tb = parse_rational(src_in["tb"])
        heard = audio if "timeline_in" in audio else e
        at = Fraction(int(heard["timeline_in"]["frames"])) / rate
        asset = int(e["asset_id"][4:])
        for word in s.scalars(
            select(TranscriptWord)
            .where(
                TranscriptWord.asset_id == asset,
                TranscriptWord.start_ticks >= a,
                TranscriptWord.end_ticks <= b,
            )
            .order_by(TranscriptWord.start_ticks)
        ):
            text = word.word.strip()
            if text:
                yield Word(at + (word.start_ticks - a) * tb, at + (word.end_ticks - a) * tb, text)


def cues(words: Iterator[Word]) -> list[tuple[Fraction, Fraction, str]]:
    """Words grouped into captions: (start, end, text with at most one line break)."""
    out: list[tuple[Fraction, Fraction, str]] = []
    group: list[Word] = []

    def close() -> None:
        if group:
            out.append((group[0].start, group[-1].end, _lines(" ".join(w.text for w in group))))
            group.clear()

    for w in words:
        if group:
            text = " ".join(x.text for x in [*group, w])
            if (
                w.start - group[-1].end >= PAUSE
                or w.end - group[0].start > MAX_CUE
                or len(text) > 2 * LINE
            ):
                close()
        group.append(w)
        if w.text[-1] in ".?!…":
            close()
    close()
    # Hold short cues a little longer, never into the next one.
    held = []
    for i, (a, b, text) in enumerate(out):
        limit = out[i + 1][0] if i + 1 < len(out) else b + MIN_CUE
        held.append((a, max(b, min(a + MIN_CUE, limit)), text))
    return held


def _lines(text: str) -> str:
    """One line, or two balanced at a space when it is longer than a line."""
    if len(text) <= LINE:
        return text
    words = text.split()
    best = min(
        range(1, len(words)),
        key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))),
        default=len(words),
    )
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def stamp(t: Fraction) -> str:
    ms = int(t * 1000)  # floor: a caption never starts late
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    sec, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def srt(s: Session, timeline: dict[str, Any]) -> str:
    """The edit's captions as SRT text (empty when nothing heard has a transcript)."""
    blocks = [
        f"{i}\n{stamp(a)} --> {stamp(b)}\n{text}\n"
        for i, (a, b, text) in enumerate(cues(heard_words(s, timeline)), 1)
    ]
    return "\n".join(blocks)
