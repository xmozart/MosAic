"""``make eval`` plumbing (M0 step 12), offline: gates, budget, one trip with the fake AI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mosaic.evaluation import expectations as exp
from mosaic.evaluation import run as ev
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB

pytestmark = [pytest.mark.integration, pytest.mark.models]


def test_unconfigured_eval_stops_at_g1_with_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.main([]) == ev.EXIT_GATE
    err = capsys.readouterr().err
    assert "G1" in err
    assert "mosaic config set eval.corpus_dir" in err
    assert "mosaic config ai set-key --provider anthropic" in err
    assert "claude-cli" in err


def test_budget_is_the_smaller_of_run_and_milestone() -> None:
    b = ev.Budget(run_usd=5.0, milestone_usd=25.0, spent_before=22.0)
    assert b.remaining == pytest.approx(3.0)
    b.spent_now = 3.5
    assert b.remaining == 0.0
    assert ev.Budget(5.0, 25.0, 0.0).remaining == 5.0


def test_one_trip_end_to_end_offline(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    trip = corpus / "Mini"
    trip.mkdir(parents=True)
    for name in ("A001_basic.mp4", "A002_basic.mp4", "accidental.mp4", "speech.mp4"):
        assert (corpus_dir / name).exists(), name
        shutil.copy2(corpus_dir / name, trip / name)
    monkeypatch.setattr(ev, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(ev, "CORPUS_META", tmp_path / "meta")
    monkeypatch.setattr(ev, "TRIP_EDITS", {"mini": {"duration_s": 30}})
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "all", "fake", "fake")
    assert ev.trips(corpus) == [trip]
    budget = ev.Budget(5.0, 25.0, 0.0)
    result = ev.run_trip(control, me, trip, budget, render=True)
    out = ev.write_results(result)

    data = json.loads(out.read_text())
    assert data["metrics"]["blocking_ok"]
    assert data["request"]["duration_s"] == 30
    assert Path(data["render"]["path"]).is_file()
    assert data["render"]["metrics"]["frames"] == data["metrics"]["total_frames"]
    assert out.with_suffix(".md").read_text().startswith("# Mini")
    drafted = exp.load(tmp_path / "meta" / "mini" / "expectations.yaml")
    assert drafted is not None
    assert drafted["draft"] is True
    assert any("accidental" in m["note"] for m in drafted["must_exclude"])
    score = data["expectations"]
    assert score["draft"] is True
    assert score["must_exclude_violations"] == 0
    # Originals untouched: only the descriptor and MosAic/ were added to the trip folder.
    added = {p.name for p in trip.iterdir()} - {
        "A001_basic.mp4",
        "A002_basic.mp4",
        "accidental.mp4",
        "speech.mp4",
    }
    assert added == {".mosaic-project.json", "MosAic"}
    ev.write_ledger({"milestone": "M0", "runs": [{"cost_usd": budget.spent_now}]})
    assert json.loads(ev.ledger_path().read_text())["runs"][0]["cost_usd"] == 0.0


def test_budget_stop_is_g2_and_counts_the_paused_job(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip = tmp_path / "corpus" / "Pricey"
    trip.mkdir(parents=True)
    # Two recordings → two vision calls: analysis spends $0.30, then pauses at the limit.
    for name in ("A001_basic.mp4", "speech.mp4"):
        shutil.copy2(corpus_dir / name, trip / name)
    monkeypatch.setattr(ev, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(ev, "CORPUS_META", tmp_path / "meta")
    monkeypatch.setenv("MOSAIC_FAKE_COST_USD", "0.3")  # every fake AI call costs $0.30
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "all", "fake", "fake")
    budget = ev.Budget(run_usd=0.5, milestone_usd=25.0, spent_before=0.0)
    with pytest.raises(ev.GateStop) as stop:
        ev.run_trip(control, me, trip, budget, render=False)
    assert stop.value.gate == "G2"
    assert "budget" in str(stop.value)
    assert 0 < budget.spent_now <= 0.5  # spend is counted, never above the budget
    from mosaic.jobs.store import JobStore

    # The job that hit the limit had spent something itself, and that spend is counted.
    stopped = [j for j in JobStore(control.db).jobs() if j.status == "cancelled"]
    assert stopped
    assert all(j.cost_usd > 0 for j in stopped)


def test_trips_under_a_parent_named_mosaic(tmp_path: Path) -> None:
    corpus = tmp_path / "MosAic" / "Samples"
    (corpus / "Trip").mkdir(parents=True)
    (corpus / "Trip" / "clip.mp4").write_bytes(b"\0")
    (corpus / "Trip" / "MosAic").mkdir()
    (corpus / "Trip" / "MosAic" / "proxy.mp4").write_bytes(b"\0")
    (corpus / "Empty").mkdir()
    assert ev.trips(corpus) == [corpus / "Trip"]


def _event(asset: int, a: int, b: int) -> dict[str, object]:
    return {
        "asset_id": f"ast_{asset:04d}",
        "source_in": {"ticks": a, "tb": "1/90000"},
        "source_out": {"ticks": b, "tb": "1/90000"},
    }


def _moment(asset: int, a: int, b: int, note: str) -> dict[str, object]:
    return {
        "file": "x.mp4",
        "asset": f"ast_{asset:04d}",
        "range": {"start": {"ticks": a, "tb": "1/90000"}, "end": {"ticks": b, "tb": "1/90000"}},
        "note": note,
    }


def test_expectation_scoring_and_blocking() -> None:
    expect = {
        "draft": False,
        "must_include": [_moment(1, 0, 900, "kept"), _moment(2, 0, 900, "missed")],
        "must_exclude": [_moment(3, 100, 200, "pocket"), _moment(1, 5000, 6000, "fine")],
    }
    events = [_event(1, 800, 2000), _event(3, 150, 400), _event(2, 900, 1800)]
    # Files are authoritative: the project's asset ids may differ from the YAML's.
    score = exp.score(expect, events, {"x.mp4": 1})
    assert score["must_include_hit"] == 2  # both "x.mp4" moments resolve to asset 1
    score = exp.score(expect, events)
    assert (score["must_include_hit"], score["must_include_total"]) == (1, 2)
    assert score["must_include_recall"] == 0.5
    assert score["must_exclude_violations"] == 1
    assert score["violations"] == ["x.mp4 pocket"]
    confirmed = {"metrics": {"blocking_ok": True}, "expectations": score}
    assert not ev.blocking_ok(confirmed)
    drafted = {"metrics": {"blocking_ok": True}, "expectations": score | {"draft": True}}
    assert ev.blocking_ok(drafted)


def test_cli_stops_following_a_paused_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import click

    from mosaic.cli import main as cli_main
    from mosaic.jobs import client
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
    from mosaic.jobs.store import JobStore

    control = ControlDB()
    store = JobStore(control.db)
    job = store.create_job(
        control.local_principal,
        JobSpec("p", "edit", tasks=[TaskSpec("x", "s", resource_class=ResourceClass.AI_API)]),
    )
    store.pause(job, cost_limit=True)
    monkeypatch.setattr(client, "ensure_worker", lambda _c: None)
    with pytest.raises(click.ClickException, match=r"ai\.budget\.per_job_usd"):
        cli_main._follow(control, job)
