"""The optional AI critic (M4: "takes the EDL plus summaries and returns structured
suggestions. It does not analyze the rendered video in v1"; ADR 0082).

After a generation is timed, the critic reads the cut as text: each shot by its event id,
with what its clip shows. Its notes name events by id only (validated against the cut);
code turns a "remove" or "replace" into the same storyboard ops the deterministic critic
uses, never for a shot the owner locked or chose (invariant 10). Its notes join the
version's findings with ``source: ai``.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, Any

from mosaic.core.time import format_display, parse_rational
from mosaic.editing import critic
from mosaic.editing.titles import shot_events

if TYPE_CHECKING:
    from mosaic.ai.prompts.critic.schema_v1 import Output
    from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
    from mosaic.editing.request import EditRequest
    from mosaic.editing.resolve import Resolved
    from mosaic.library.context import TripContext

CRITIC = ("critic", 1)
CRITIC_MAX_TOKENS = 2000
SETTING = "editing.ai_critic"


def context(req: EditRequest, trip: TripContext, plan: PlanOut, done: Resolved) -> dict[str, Any]:
    """The prompt's context: the plan, the cut as one line per shot, and the checks."""
    from mosaic.editing.generate import request_summary

    rate = parse_rational(done.timeline["rate"])
    lines = []
    for e, c in zip(shot_events(done.timeline["tracks"][0]["events"]), done.cuts, strict=True):
        o = c.shot.cand.obs
        a, b = e["timeline_in"]["frames"], e["timeline_out"]["frames"]
        parts = [
            e["event_id"],
            f"{format_display(Fraction(a) / rate)}",
            e.get("beat_id") or "-",
            e.get("role") or "-",
            f"{float(Fraction(b - a) / rate):.1f}s",  # display only
            "photo: " + o.get("description", "?")
            if c.shot.cand.still
            else o.get("description", "(no description)"),
            f"interest {o.get('interest', '?')}",
        ]
        if c.shot.dialogue:
            parts.append("speech")
        lines.append(" · ".join(parts))
    return {
        "trip_context": trip.prompt_text(),
        "request": request_summary(req),
        "beats": "\n".join(f"{b.beat_id}: {b.title} - {b.intent}" for b in plan.beats),
        "events": "\n".join(lines),
        "event_count": len(lines),
        "checks": "\n".join(f"- {f.text}" for f in done.findings) or "(nothing)",
        # For the offline fake adapter only (never in the prompt text).
        "event_ids": [e["event_id"] for e in shot_events(done.timeline["tracks"][0]["events"])],
    }


def check(answer: Output, shots: set[str]) -> list[str]:
    """Errors in an otherwise schema-valid answer: unknown events, actions without one."""
    errors = []
    for n in answer.notes:
        if n.event_id is not None and n.event_id not in shots:
            errors.append(f"{n.event_id} is not a shot of this cut")
        if n.action != "note" and n.event_id is None:
            errors.append(f'"{n.action}" needs the event_id of the shot')
    return errors


def findings(answer: Output, done: Resolved) -> list[critic.Finding]:
    """The critic's notes as findings, each with the fix for its shot when it has one."""
    events = shot_events(done.timeline["tracks"][0]["events"])
    by_event = {e["event_id"]: (e, c) for e, c in zip(events, done.cuts, strict=True)}
    used = {sh.cand.ref for c in done.cuts for sh in (c.shot, *c.merged_shots)}
    out = []
    for n in answer.notes:
        e, c = by_event.get(n.event_id, (None, None)) if n.event_id else (None, None)
        ops = None
        if c is not None and n.action == "replace":
            ops = critic.fix_for(c, used, remove=False)
        elif c is not None and n.action == "remove" and critic.fixable(c):
            ops = [{"kind": "remove_shot", "ref": c.merged_refs[0]}]  # as the critic said
        out.append(
            critic.Finding(
                f"ai_{n.action}",
                n.severity,
                int(e["timeline_in"]["frames"]) if e else 0,
                n.text,
                ref=c.merged_refs[0] if c is not None else None,
                ops=ops,
                event_id=n.event_id if e else None,
                source="ai",
            )
        )
    return out
