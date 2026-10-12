"""Critic v2 (ADR 0081): findings about a shot name it and carry the fix as storyboard
ops - never for a shot the owner locked or chose."""

from __future__ import annotations

import dataclasses

from mosaic.editing import critic, draft
from tests.unit.test_editing import RATE, _cut, cand


def _findings(cuts: list) -> list[critic.Finding]:  # type: ignore[type-arg]
    return critic.evaluate(cuts, 900, 45, RATE, set(), {1}, ["b1"])[1]


def _alts(cut, *segs: str):  # type: ignore[no-untyped-def]
    cut.shot.alternatives = [{"segment_id": s, "why_not": "Softer"} for s in segs]
    return cut


def test_a_repeat_is_fixed_by_an_unused_alternative_or_by_removing_it() -> None:
    a = _cut(cand(1, asset=1, group=7), 0, 3)
    b = _cut(cand(2, asset=2, group=8), 0, 3)
    c = _alts(_cut(cand(3, asset=3, group=7), 0, 3), "seg_000001", "seg_000009")
    rep = next(f for f in _findings([a, b, c]) if f.code == "repetition")
    assert rep.ref == c.merged_refs[0], "the later shot is the one that goes"
    assert rep.frame == 2 * a.frames
    assert rep.ops == [{"kind": "replace_shot", "ref": rep.ref, "segment_id": "seg_000009"}]
    plain = _cut(cand(4, asset=4, group=7), 0, 3)
    rep = next(f for f in _findings([a, plain]) if f.code == "repetition")
    assert rep.ops == [{"kind": "remove_shot", "ref": plain.merged_refs[0]}]
    for op in rep.ops:
        draft.OP.validate_python(op)  # every fix is a real storyboard op


def test_a_locked_or_chosen_shot_gets_no_fix() -> None:
    a = _cut(cand(1, asset=1, group=7), 0, 3)
    locked = _cut(cand(2, asset=2, group=7), 0, 3, locked=True)
    chosen = _cut(cand(3, asset=3, group=7, user_use=True), 0, 3)
    reps = [f for f in _findings([a, locked, chosen]) if f.code == "repetition"]
    assert reps
    assert all(f.ops is None for f in reps)


def test_a_very_shaky_shot_is_a_finding_with_a_steadier_alternative() -> None:
    steady = _cut(cand(1, asset=1), 0, 3)
    shaky = _alts(_cut(cand(2, asset=2), 0, 3), "seg_000005")
    shaky.shot.cand = dataclasses.replace(shaky.shot.cand, shake_percentile=0.95)
    lone = _cut(cand(3, asset=3), 0, 3)
    lone.shot.cand = dataclasses.replace(lone.shot.cand, shake_percentile=0.97)
    found = [f for f in _findings([steady, shaky, lone]) if f.code == "shaky_shot"]
    assert [(f.ref, f.severity) for f in found] == [
        (shaky.merged_refs[0], "warning"),
        (lone.merged_refs[0], "info"),
    ]
    assert found[0].ops == [
        {"kind": "replace_shot", "ref": shaky.merged_refs[0], "segment_id": "seg_000005"}
    ]
    assert found[1].ops is None, "no alternative: a note, nothing to apply"
    j = found[0].as_json()
    assert j["ops"] == found[0].ops
    assert "event_id" not in j


def test_three_alike_make_one_finding_each_and_never_share_an_alternative() -> None:
    a = _cut(cand(1, asset=1, group=7), 0, 3)
    b = _alts(_cut(cand(2, asset=2, group=7), 0, 3), "seg_000009")
    c = _alts(_cut(cand(3, asset=3, group=7), 0, 3), "seg_000009", "seg_000010")
    reps = [f for f in _findings([a, b, c]) if f.code == "repetition"]
    assert [f.ref for f in reps] == [b.merged_refs[0], c.merged_refs[0]]
    assert [f.ops[0].get("segment_id") for f in reps if f.ops] == ["seg_000009", "seg_000010"]


def test_a_pinned_or_merged_locked_shot_gets_no_fix_and_a_photo_is_never_shaky() -> None:
    a = _cut(cand(1, asset=1, group=7), 0, 3)
    pinned = _cut(cand(2, asset=2, group=7), 0, 3)
    pinned.shot.pin = (0, 270270, 90)
    merged = _cut(cand(3, asset=3, group=7), 0, 3)
    held = _cut(cand(4, asset=3), 3, 3, locked=True)
    merged.merged_shots = [held.shot]
    reps = [f for f in _findings([a, pinned, merged]) if f.code == "repetition"]
    assert len(reps) == 2
    assert all(f.ops is None for f in reps)
    photo = _cut(cand(5, asset=5), 0, 3)
    photo.shot.cand = dataclasses.replace(photo.shot.cand, still=True, shake_percentile=0.99)
    assert not [f for f in _findings([photo]) if f.code == "shaky_shot"]


def test_the_ai_critics_answer_names_shots_of_this_cut_only() -> None:
    import pytest
    from pydantic import ValidationError

    from mosaic.ai.prompts.critic.schema_v1 import Output
    from mosaic.ai.prompts.loader import load
    from mosaic.editing import ai_critic

    prompt = load(*ai_critic.CRITIC)
    keys = ("trip_context", "request", "beats", "events", "event_count", "checks")
    system, _ = prompt.render(dict.fromkeys(keys, "x"))
    assert "event_id" in system
    assert "timecodes" in system, "no timing in the answer (invariant 5)"
    with pytest.raises(ValidationError):
        Output.model_validate(
            {
                "notes": [
                    {"event_id": "evt_1", "action": "note", "severity": "info", "text": "x" * 20}
                ]
            }
        )
    answer = Output.model_validate(
        {
            "notes": [
                {"event_id": "evt_0009", "action": "note", "severity": "info", "text": "y" * 20},
                {"event_id": None, "action": "remove", "severity": "warning", "text": "z" * 20},
            ]
        }
    )
    assert ai_critic.check(answer, {"evt_0001"}) == [
        "evt_0009 is not a shot of this cut",
        '"remove" needs the event_id of the shot',
    ]


def test_the_ai_critic_never_fixes_a_locked_shot() -> None:
    from mosaic.ai.prompts.critic.schema_v1 import Output
    from mosaic.editing import ai_critic, refiner
    from mosaic.editing.resolve import Resolved

    free = _alts(_cut(cand(1, asset=1), 0, 3), "seg_000008")
    locked = _cut(cand(2, asset=2), 0, 3, locked=True)
    cuts = [free, locked]
    events = refiner.events(cuts, RATE)
    done = Resolved({"rate": RATE, "tracks": [{"events": events}]}, [], {}, [], cuts)
    answer = Output.model_validate(
        {
            "notes": [
                {"event_id": "evt_0001", "action": "replace", "severity": "info", "text": "a" * 20},
                {
                    "event_id": "evt_0002",
                    "action": "remove",
                    "severity": "warning",
                    "text": "b" * 20,
                },
            ]
        }
    )
    got = ai_critic.findings(answer, done)
    assert got[0].ops == [
        {"kind": "replace_shot", "ref": free.merged_refs[0], "segment_id": "seg_000008"}
    ]
    assert got[1].ops is None, "the owner's lock wins (invariant 10)"
    assert {f.source for f in got} == {"ai"}
    assert got[1].as_json()["source"] == "ai"
