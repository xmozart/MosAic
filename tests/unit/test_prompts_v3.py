"""Planner and selector v3 (ADR 0073): the M4 request reaches the prompts as words, the
owner's custom beats are enforced, and the prompt files render with their context."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mosaic.ai.prompts.loader import load
from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
from mosaic.editing.generate import PLANNER, SELECTOR, arc_text, check_plan, preferences_text
from mosaic.editing.request import EditRequest


def _plan(*titles: str) -> PlanOut:
    return PlanOut.model_validate(
        {
            "title": "Trip",
            "beats": [
                {
                    "beat_id": f"b{i}",
                    "title": t,
                    "intent": "x x x",
                    "share_percent": 100 // len(titles),
                    "candidates": ["seg_000001"],
                }
                for i, t in enumerate(titles, 1)
            ],
        }
    )


def test_the_arc_is_a_template_or_the_owners_beats() -> None:
    assert arc_text(EditRequest(duration_s=60)).startswith("Classic travel arc")
    assert arc_text(EditRequest(duration_s=60, arc="documentary")).startswith("Documentary")
    custom = EditRequest(duration_s=60, arc="custom", beats=["Arrival", "The reef", "Home"])
    assert "exactly these 3, in this order" in arc_text(custom)
    assert "1. Arrival; 2. The reef; 3. Home" in arc_text(custom)
    with pytest.raises(ValidationError, match="at least two beats"):
        EditRequest(duration_s=60, arc="custom", beats=["Only one"])


def test_a_plan_must_follow_the_owners_beats() -> None:
    req = EditRequest(duration_s=60, arc="custom", beats=["Arrival", "The reef"])
    refs = {"seg_000001"}
    assert check_plan(_plan("Arrival", "the reef"), refs, req) == []
    assert check_plan(_plan("The reef", "Arrival"), refs, req)
    assert check_plan(_plan("Arrival", "Reef", "Home"), refs, req)
    assert check_plan(_plan("Anything", "Else"), refs, EditRequest(duration_s=60)) == []


def test_preferences_as_words() -> None:
    req = EditRequest(
        duration_s=60,
        weights={"wildlife": "strong", "slow_motion": "more", "selfies": "avoid", "city": "less"},
        rules={"drone_openers": True, "unique_over_quality": False, "avoid_repetition": False},
        audio={"keep_dialogue": True, "natural_sound": False, "reduce_wind": False},
        shot_lengths={"min_ds": 15, "preferred_ds": 40, "max_ds": 90},
    )
    text = preferences_text(req)
    assert "Strongly prefer: wildlife." in text
    assert "More of: slow motion." in text
    assert "Less of: city." in text
    assert "Avoid: selfies." in text
    assert "drone shot" in text
    assert "technically clean shots" in text
    assert "no near-identical" not in text
    assert "never cut someone mid-sentence" in text
    assert "natural sound" not in text
    assert "about 4 s, from 1.5 s to 9 s" in text
    plain = preferences_text(EditRequest(duration_s=60))
    assert "Avoid repetition" in plain
    assert "unique moments" in plain


def test_v3_prompts_render_with_their_context() -> None:
    assert PLANNER == ("planner", 3)
    assert SELECTOR == ("selector", 3)
    ctx = {
        "trip_context": "(none)",
        "request": "60 s",
        "arc": "Classic travel arc",
        "preferences": "More of: wildlife.",
        "instructions": "(none)",
        "days": "day 1",
        "candidate_count": 1,
        "candidates": "seg_000001 · day 1",
        "pace": "balanced",
        "beats": "## b1",
    }
    _, user = load(*PLANNER).render(ctx)
    assert "Arc: Classic travel arc" in user
    assert "More of: wildlife." in user
    _, user = load(*SELECTOR).render(ctx)
    assert "More of: wildlife." in user


def test_custom_beats_fit_the_planners_titles() -> None:
    with pytest.raises(ValidationError, match="2–60 characters"):
        EditRequest(duration_s=60, arc="custom", beats=["A", "Home"])
    with pytest.raises(ValidationError, match="2–60 characters"):
        EditRequest(duration_s=60, arc="custom", beats=["x" * 61, "Home"])
    titles = [f"Day {i} on the island" for i in range(1, 11)]
    req = EditRequest(duration_s=600, arc="custom", beats=titles)
    plan = _plan(*(t.upper() for t in titles))  # ten beats, the planner's schema allows it
    assert check_plan(plan, {"seg_000001"}, req) == []
    from mosaic.editing.generate import owners_titles

    assert [b.title for b in owners_titles(plan, req).beats] == titles, "as the owner typed"
    system = load(*PLANNER).system
    assert "plan exactly that many instead" in system
