"""Deterministic critic (ARCHITECTURE.md §9, EVALUATION.md §2): metrics and findings.

Zero-target metrics: duration outside tolerance, mid-word cuts (audible cuts inside a
word), dialogue truncations (a dialogue shot ending inside a sentence), adjacent jump cuts
and REJECT segments used without a user lock. Also reported: repetition of a similarity
group within 5 events, the shake percentile of used shots, and day and beat coverage.
v2 (M4; ADR 0081): a finding about one shot names it and carries the storyboard ops that
fix it (an unused alternative, or removing the shot), never for a shot the owner locked
or chose; very shaky shots are findings too.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from mosaic.core.time import parse_rational
from mosaic.editing.refiner import Cut, inside, is_jump, margin_ticks

REPEAT_WINDOW = 5


SHAKY = 0.9  # a shot shakier than 90 % of the project's is worth replacing


@dataclass(frozen=True)
class Finding:
    """A critic finding. ``ref``: the shot it is about (its selection ref), when it is
    about one; ``ops``: the storyboard ops (``draft.Op`` as JSON) that would fix it, None
    when there is nothing to apply (ADR 0081). ``event_id`` is filled in once the
    timeline's events exist."""

    code: str
    severity: str  # blocking|warning|info
    frame: int
    text: str
    ref: str | None = None
    ops: list[dict[str, Any]] | None = None
    event_id: str | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "frame": self.frame,
            "text": self.text,
        }
        if self.event_id:
            out["event_id"] = self.event_id
        if self.ops:
            out["ops"] = self.ops
        return out


def fix_for(c: Cut, used: set[str], *, remove: bool) -> list[dict[str, Any]] | None:
    """Ops that take shot ``c`` out of the edit: its first alternative that is not in the
    edit already, else (``remove``) dropping it. None for a shot the owner locked or
    chose (invariant 10), or one cut together with such a shot. The alternative chosen
    joins ``used``, so no two fixes offer the same one."""
    for sh in (c.shot, *c.merged_shots):
        if sh.locked or sh.cand.user_use or sh.pin is not None:
            return None
    ref = c.merged_refs[0]
    alt = next((a["segment_id"] for a in c.shot.alternatives if a["segment_id"] not in used), None)
    if alt is not None:
        used.add(alt)
        return [{"kind": "replace_shot", "ref": ref, "segment_id": alt}]
    return [{"kind": "remove_shot", "ref": ref}] if remove else None


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
        heard_in, heard_out = c.heard  # a J- or L-cut moves only the picture (ADR 0077)
        for t, where in ((heard_in, "starts"), (heard_out, "ends")):
            if any(inside(t, w, m) for w in c.ctx.words):
                mid_word += 1
                findings.append(
                    Finding("mid_word", "blocking", at, f"{c.shot.cand.ref} {where} inside a word")
                )
        if c.shot.audio_intent == "dialogue" and any(
            inside(heard_out, s, m) for s in c.ctx.sentences
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

    used = {sh.cand.ref for c in cuts for sh in (c.shot, *c.merged_shots)}
    repeats = 0
    flagged: set[int] = set()  # a later shot is one finding, however many it repeats
    for i, c in enumerate(cuts):
        g = c.shot.cand.group_id
        if g is None:
            continue
        for j in range(i + 1, min(len(cuts), i + REPEAT_WINDOW)):
            d = cuts[j]
            if d.shot.cand.group_id == g:
                repeats += 1
                if j in flagged:
                    continue
                flagged.add(j)
                # The later one goes: replaced by an alternative, or dropped.
                findings.append(
                    Finding(
                        "repetition",
                        "warning",
                        starts[j],
                        f"{d.shot.cand.ref} looks like {c.shot.cand.ref}, shown just before",
                        ref=d.merged_refs[0],
                        ops=fix_for(d, used, remove=True),
                    )
                )
    minutes = Fraction(total) / parse_rational(rate) / 60
    repeats_per_5min = float(Fraction(repeats) / max(minutes / 5, Fraction(1, 5)))

    shakes = [
        c.shot.cand.shake_percentile for c in cuts if c.shot.cand.shake_percentile is not None
    ]
    shake_median = statistics.median(shakes) if shakes else None
    for c, at in zip(cuts, starts, strict=True):
        p = c.shot.cand.shake_percentile
        if p is not None and p >= SHAKY and not c.shot.cand.still:
            ops = fix_for(c, used, remove=False)
            findings.append(
                Finding(
                    "shaky_shot",
                    "warning" if ops else "info",
                    at,
                    f"{c.shot.cand.ref} is shakier than most of the trip"
                    + ("; an alternative is steadier" if ops else ""),
                    ref=c.merged_refs[0],
                    ops=ops,
                )
            )
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
