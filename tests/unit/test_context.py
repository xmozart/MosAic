"""Trip context (M1 step 1): model, prompt text, prompts v2."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mosaic.ai.prompts.loader import load
from mosaic.library.context import TripContext


def test_context_validation_and_text() -> None:
    assert TripContext().is_empty()
    assert TripContext().prompt_text() == "(none)"
    ctx = TripContext.model_validate(
        {
            "trip_name": "Lakeshore Airshow 2026",
            "home_timezone": "America/Toronto",
            "days": [{"date": "2026-09-06", "place": "Waterfront", "notes": "Main show"}],
            "people": [{"label": "Michael", "description": "orange cap"}],
            "must_include": ["the F-35 demonstration"],
            "avoid": ["long crowd shots"],
            "free_notes": "An airshow over the lake; aircraft are the main subject.",
        }
    )
    text = ctx.prompt_text()
    for part in ("Lakeshore Airshow 2026", "F-35", "long crowd shots", "orange cap", "2026-09-06"):
        assert part in text
    assert ctx.digest() == TripContext.model_validate(ctx.model_dump()).digest()
    assert ctx.digest() != TripContext(free_notes="x").digest()
    with pytest.raises(ValidationError, match="time zone"):
        TripContext(home_timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        TripContext.model_validate({"days": [{"date": "not-a-date"}]})
    with pytest.raises(ValidationError):
        TripContext.model_validate({"unknown_field": 1})


def test_prompts_v2_carry_the_context_and_v1_is_unchanged() -> None:
    ctx = TripContext(free_notes="An airshow; aircraft are the main subject.").prompt_text()
    for name in ("planner", "selector"):
        v2 = load(name, 2)
        base = {
            "trip_context": ctx,
            "request": "r",
            "instructions": "(none)",
            "days": "",
            "candidate_count": 0,
            "candidates": "",
            "pace": "balanced",
            "beats": "",
        }
        _, user = v2.render(base)
        assert "aircraft are the main subject" in user
        system, _ = v2.render(base)
        assert "trip context" in system
        v1_system, _ = load(name, 1).render(base)
        assert "trip context" not in v1_system  # versions are immutable
    parse = load("context_parse", 1)
    system, user = parse.render({"text": "We went to the airshow.", "today": "2026-10-05"})
    assert "Never invent" in system
    assert "We went to the airshow." in user


def test_dates_are_stored_canonical() -> None:
    assert TripContext.model_validate({"days": [{"date": "20260906"}]}).days[0].date == "2026-09-06"


def test_subject_shares() -> None:
    from mosaic.evaluation.expectations import subject_shares

    def ev(seg: str, a: int, b: int) -> dict[str, object]:
        return {"segment_id": seg, "timeline_in": {"frames": a}, "timeline_out": {"frames": b}}

    events = [ev("seg_1", 0, 30), ev("seg_2", 30, 90), ev("seg_3", 90, 100)]
    desc = {
        "seg_1": "An F-35 Jet over the lake",
        "seg_2": "A crowd of spectators watching a jet",
        "seg_3": "Boats",
    }
    expect = {"subjects": {"aircraft": ["jet", "f-35"], "crowd": ["crowd"]}}
    shares = subject_shares(expect, events, desc)
    assert shares == {"aircraft": 0.9, "crowd": 0.6}  # frame-weighted, overlapping, any case
    assert subject_shares({}, events, desc) == {}


def test_context_api_and_cli(tmp_path: Path) -> None:
    import json

    from click.testing import CliRunner
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.cli.main import cli
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project

    folder = tmp_path / "trip"
    folder.mkdir()
    control = ControlDB()
    project = init_project(control, control.local_principal, folder)
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    url = f"/api/projects/{project.id}/trip-context"
    empty = client.get(url).json()
    assert empty["revision"] == 0
    assert empty["free_notes"] == ""
    first = client.put(url, json={"free_notes": "An airshow.", "must_include": ["F-35"]})
    assert first.json()["revision"] == 1
    again = client.put(url, json=client.get(url).json() | {"avoid": ["crowds"]})
    assert again.json()["revision"] == 2
    for bad in ({"nope": 1}, {"home_timezone": "Mars/Base"}, {"days": [{"date": "x"}]}):
        assert client.put(url, json=bad).status_code == 422
    parse = client.post(url + "/parse", json={"text": "We saw an airshow."})
    assert parse.status_code == 202
    assert "job_id" in parse.json()
    assert client.get(url).json()["revision"] == 2, "parsing proposes, it never saves"
    project.close()

    runner = CliRunner()
    good = tmp_path / "ctx.json"
    good.write_text(json.dumps({"trip_name": "Show", "free_notes": "Aircraft."}))
    out = runner.invoke(cli, ["context", "set", str(folder), "--file", str(good)])
    assert out.exit_code == 0, out.output
    shown = runner.invoke(cli, ["context", "show", str(folder)])
    assert json.loads(shown.output)["trip_name"] == "Show"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    out = runner.invoke(cli, ["context", "set", str(folder), "--file", str(bad)])
    assert out.exit_code != 0
    assert "not valid JSON" in out.output
    bad.write_text(json.dumps({"home_timezone": "Mars/Base"}))
    out = runner.invoke(cli, ["context", "set", str(folder), "--file", str(bad)])
    assert "invalid trip context" in out.output
    assert runner.invoke(cli, ["context", "clear", str(folder)]).exit_code == 0
    assert (
        json.loads(runner.invoke(cli, ["context", "show", str(folder)]).output)["trip_name"] == ""
    )


def test_best_frame_must_exist() -> None:
    from types import SimpleNamespace

    from mosaic.library.review import check_best_frame

    assert check_best_frame(SimpleNamespace(best_frame="F3"), 3) == []
    assert "does not exist" in check_best_frame(SimpleNamespace(best_frame="F7"), 3)[0]
