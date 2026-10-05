"""Solver (ARCHITECTURE.md §9): exact shot lengths and order from the AI's decisions.

Pure integer arithmetic in timeline frames:

1. each selection's length class becomes a desired length from the pace, clamped to what
   the clip offers (its usable range) and to the pace's maximum (dialogue may run longer);
2. while the edit is too long, the lowest-priority shot of the beat furthest over its
   budget is dropped, as long as the edit stays at or above the target; locked shots and
   a beat's last shot are never dropped;
3. lengths are then trimmed or extended, frame by frame, toward the exact target;
4. if the material cannot reach the target within tolerance, that is reported
   (``underfilled``) rather than hidden.

Order follows the requested chronology. Nothing here calls AI (invariant 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.editing.request import PaceFrames
from mosaic.editing.retrieval import Candidate


@dataclass
class Shot:
    cand: Candidate
    beat_id: str
    beat_index: int
    order: int  # selector order within the beat
    role: str
    priority: int
    length: str
    audio_intent: str
    reason: str
    alternatives: list[dict[str, str]] = field(default_factory=list)
    locked: bool = False
    frames: int = 0
    lo: int = 0
    hi: int = 0
    alt_of: str | None = None  # a selector-named alternative to that selection
    alt_index: int = 0

    @property
    def dialogue(self) -> bool:
        return self.audio_intent == "dialogue" and self.cand.has_speech

    @property
    def selection_ref(self) -> str:
        if self.alt_of is not None:
            return f"{self.alt_of}~alt{self.alt_index}"
        return f"{self.beat_id}#{self.order}"


@dataclass
class Fit:
    shots: list[Shot]
    dropped: list[Shot]
    total: int
    target: int
    tolerance: int
    underfilled: bool
    notes: list[str]


def available_frames(c: Candidate, rate: str) -> int:
    return round_fraction(c.usable_seconds * parse_rational(rate), Rounding.FLOOR)


def desired_frames(length: str, pace: PaceFrames, dialogue: bool) -> int:
    if dialogue:
        return pace.dialogue_max
    return {
        # integer arithmetic: 0.6 × and 1.6 × preferred, rounded half up
        "short": max(pace.min, (pace.preferred * 3 + 2) // 5),
        "medium": pace.preferred,
        "long": min(pace.max, (pace.preferred * 8 + 2) // 5),
        "hold": pace.max,
    }[length]


def bounds(shot: Shot, pace: PaceFrames, rate: str) -> tuple[int, int]:
    avail = available_frames(shot.cand, rate)
    hi = min(avail, pace.dialogue_max if shot.dialogue else pace.max)
    lo = min(pace.min, hi)
    return lo, hi


def fit(
    shots: list[Shot],
    beat_shares: dict[str, int],
    target: int,
    tolerance: int,
    pace: PaceFrames,
    rate: str,
) -> Fit:
    notes: list[str] = []
    kept: list[Shot] = []
    dropped: list[Shot] = []
    for s in shots:
        s.lo, s.hi = bounds(s, pace, rate)
        if s.hi < pace.min and not (s.locked or s.cand.user_use):
            dropped.append(s)
            notes.append(f"{s.cand.ref}: usable range shorter than the minimum shot")
            continue
        s.frames = max(s.lo, min(s.hi, desired_frames(s.length, pace, s.dialogue)))
        kept.append(s)

    share_total = sum(beat_shares.values()) or 1
    budget = {b: Fraction(target * p, share_total) for b, p in beat_shares.items()}

    def total() -> int:
        return sum(s.frames for s in kept)

    # 2. drop by priority while the edit stays at or above the target
    while total() > target + tolerance:
        per_beat: dict[str, list[Shot]] = {}
        for s in kept:
            per_beat.setdefault(s.beat_id, []).append(s)
        options = []
        for b, items in per_beat.items():
            droppable = [s for s in items if not s.locked and not s.cand.user_use]
            if len(items) <= 1 or not droppable:
                continue
            over = sum(s.frames for s in items) - budget.get(b, Fraction(0))
            victim = min(droppable, key=lambda s: (s.priority, -s.order))
            options.append((over, victim))
        options = [(o, v) for o, v in options if total() - v.frames >= target]
        if not options:
            break
        _, victim = max(options, key=lambda ov: (ov[0], -ov[1].priority, ov[1].order))
        kept.remove(victim)
        dropped.append(victim)
        notes.append(f"{victim.cand.ref}: dropped (priority {victim.priority}) to fit")

    # 3. trim or extend frame by frame toward the exact target (largest room first)
    diff = target - total()
    while diff != 0:
        if diff > 0:
            room = [s for s in kept if s.frames < s.hi]
            if not room:
                break
            room.sort(key=lambda s: (s.frames - s.hi, -s.priority, s.order))
            step = min(diff, max(1, diff // len(room)))
            for s in room:
                add = min(step, s.hi - s.frames, diff)
                s.frames += add
                diff -= add
                if diff == 0:
                    break
        else:
            room = [s for s in kept if s.frames > s.lo]
            if not room:
                break
            room.sort(key=lambda s: (s.lo - s.frames, s.priority, -s.order))
            step = min(-diff, max(1, -diff // len(room)))
            for s in room:
                cut = min(step, s.frames - s.lo, -diff)
                s.frames -= cut
                diff += cut
                if diff == 0:
                    break
    final = total()
    underfilled = final < target - tolerance
    if underfilled:
        notes.append(
            f"not enough usable footage: {final} of {target} frames after extending every shot"
        )
    return Fit(kept, dropped, final, target, tolerance, underfilled, notes)


def order_shots(shots: list[Shot], chronology: str) -> list[Shot]:
    """``strict``: by capture time; ``mostly``: beats in plan order, capture time within a
    beat; ``thematic``/``story``: the selector's order."""
    if chronology == "strict":
        return sorted(shots, key=lambda s: (s.cand.sort_key(), s.beat_index, s.order))
    if chronology == "mostly":
        return sorted(shots, key=lambda s: (s.beat_index, s.cand.sort_key(), s.order))
    return sorted(shots, key=lambda s: (s.beat_index, s.order))


def describe(fit_: Fit) -> dict[str, Any]:
    return {
        "target_frames": fit_.target,
        "total_frames_before_refine": fit_.total,
        "tolerance_frames": fit_.tolerance,
        "underfilled": fit_.underfilled,
        "dropped": [s.cand.ref for s in fit_.dropped],
        "notes": fit_.notes,
    }
