"""Deterministic critic (ARCHITECTURE.md §9, EVALUATION.md §2): metrics and findings.

Zero-target metrics: duration outside tolerance, mid-word cuts (audible cuts inside a
word), dialogue truncations (a dialogue shot ending inside a sentence), adjacent jump cuts
and REJECT segments used without a user lock. Also reported: repetition of a similarity
group within 5 events, the shake percentile of used shots, and day and beat coverage.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from mosaic.core.time import parse_rational
from mosaic.editing.refiner import Cut, inside, is_jump, margin_ticks

REPEAT_WINDOW = 5


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # blocking|warning|info
    frame: int
    text: str

    def as_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "frame": self.frame,
            "text": self.text,
        }


def evaluate(
    cuts: list[Cut],
    target: int,
    tolerance: int,
    rate: str,
    rejected: set[int],
    days_available: set[int],
    beat_ids: list[str],
) -> tuple[dict[str, Any], list[Finding]]:
    findings: list[Finding] = []
    starts = []
    pos = 0
    for c in cuts:
        starts.append(pos)
        pos += c.frames
    total = pos

    error = total - target
    if abs(error) > tolerance:
        findings.append(
            Finding("duration", "blocking", 0, f"duration is {error:+d} frames off the target")
        )

    mid_word = 0
    truncations = 0
    for c, at in zip(cuts, starts, strict=True):
        if c.shot.audio_intent == "mute":
            continue
        m = margin_ticks(c.tb)
        for t, where in ((c.src_in, "starts"), (c.src_out, "ends")):
            if any(inside(t, w, m) for w in c.ctx.words):
                mid_word += 1
                findings.append(
                    Finding("mid_word", "blocking", at, f"{c.shot.cand.ref} {where} inside a word")
                )
        if c.shot.audio_intent == "dialogue" and any(
            inside(c.src_out, s, m) for s in c.ctx.sentences
        ):
            truncations += 1
            findings.append(
                Finding(
                    "dialogue_truncation",
                    "blocking",
                    at + c.frames,
                    f"{c.shot.cand.ref} ends before its sentence does",
                )
            )

    jumps = 0
    for i in range(1, len(cuts)):
        if is_jump(cuts[i - 1], cuts[i]):
            jumps += 1
            findings.append(
                Finding("jump_cut", "blocking", starts[i], f"jump cut into {cuts[i].shot.cand.ref}")
            )

    reject_used = 0
    for c, at in zip(cuts, starts, strict=True):
        if c.shot.cand.segment_id in rejected and not c.shot.locked:
            reject_used += 1
            findings.append(Finding("reject_used", "blocking", at, f"{c.shot.cand.ref} is REJECT"))

    repeats = 0
    for i, c in enumerate(cuts):
        g = c.shot.cand.group_id
        if g is None:
            continue
        for d in cuts[i + 1 : i + REPEAT_WINDOW]:
            if d.shot.cand.group_id == g:
                repeats += 1
                findings.append(
                    Finding(
                        "repetition",
                        "warning",
                        starts[i],
                        f"{c.shot.cand.ref} and {d.shot.cand.ref} look alike",
                    )
                )
    minutes = Fraction(total) / parse_rational(rate) / 60
    repeats_per_5min = float(Fraction(repeats) / max(minutes / 5, Fraction(1, 5)))

    shakes = [
        c.shot.cand.shake_percentile for c in cuts if c.shot.cand.shake_percentile is not None
    ]
    shake_median = statistics.median(shakes) if shakes else None
    if shake_median is not None and shake_median > 0.5:
        findings.append(
            Finding("shake", "warning", 0, "used shots are shakier than the project median")
        )

    days_used = {c.shot.cand.day for c in cuts if c.shot.cand.day}
    beats_used = {c.shot.beat_id for c in cuts}
    for b in beat_ids:
        if b not in beats_used:
            findings.append(Finding("beat_coverage", "warning", 0, f"beat {b} has no shots"))

    metrics: dict[str, Any] = {
        "target_frames": target,
        "total_frames": total,
        "duration_error_frames": error,
        "tolerance_frames": tolerance,
        "duration_ok": abs(error) <= tolerance,
        "events": len(cuts),
        "mid_word_cuts": mid_word,
        "dialogue_truncations": truncations,
        "adjacent_jump_cuts": jumps,
        "reject_used": reject_used,
        "same_group_within_5": repeats,
        "same_group_per_5min": round(repeats_per_5min, 2),
        # Percentiles are project-normalized: 0.5 is the project median (lower is steadier).
        "shake_percentile_median": None if shake_median is None else round(shake_median, 3),
        "days_used": sorted(days_used),
        "days_available": sorted(days_available),
        "beats_used": [b for b in beat_ids if b in beats_used],
        "beats_planned": beat_ids,
    }
    metrics["blocking_ok"] = (
        metrics["duration_ok"]
        and mid_word == 0
        and truncations == 0
        and jumps == 0
        and reject_used == 0
    )
    return metrics, findings
