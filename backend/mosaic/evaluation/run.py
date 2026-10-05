"""``make eval``: M0 evaluation on the owner's real corpus (EVALUATION.md, M0.md §Evaluation).

For each trip folder under the ``eval.corpus_dir`` setting: analyze (cached artifacts make
re-runs cheap), draft expectations if the repo has none, generate the trip's edit, render
it at 1080p from the originals, then record the deterministic metrics, the expectations
score, cost and versions in ``tests/evaluation/results/M0/``.

Writes inside a trip folder are limited to ``.mosaic-project.json`` and ``MosAic/``
(AGENT_WORKFLOW.md); originals are never modified. Real AI spend is capped per run ($5)
and per milestone ($25) through job cost limits and a ledger; when configuration is
missing the run stops with gate G1 and the exact ``mosaic config`` commands.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mosaic.core.clock import now_iso
from mosaic.core.principal import Principal
from mosaic.editing.request import EditRequest
from mosaic.evaluation import expectations as exp
from mosaic.jobs.client import ensure_worker, wait_for_job
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.model import JobProgress
from mosaic.jobs.store import JobStore
from mosaic.media.scan import VIDEO_EXT
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.control import ControlDB

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "tests" / "evaluation" / "results"
CORPUS_META = REPO / "tests" / "evaluation" / "corpus"
MILESTONE = "M1"
EXIT_GATE = 3  # stopped at a human gate (G1/G2)

# The M0 edits (M0.md acceptance 3). Other trips get a 60 s cinematic journey.
TRIP_EDITS: dict[str, dict[str, Any]] = {
    "airshow": {"duration_s": 180, "story": "cinematic_journey", "chronology": "mostly"},
    "dubai": {"duration_s": 75, "story": "cinematic_journey", "chronology": "mostly"},
}
DEFAULT_EDIT: dict[str, Any] = {"duration_s": 60, "story": "cinematic_journey"}


class GateStop(Exception):  # noqa: N818 - control flow for a human gate
    def __init__(self, gate: str, message: str) -> None:
        super().__init__(f"{gate}: {message}")
        self.gate = gate


@dataclass
class Budget:
    run_usd: float
    milestone_usd: float
    spent_before: float  # this milestone, previous runs
    spent_now: float = 0.0

    @property
    def remaining(self) -> float:
        return max(
            0.0,
            min(
                self.run_usd - self.spent_now,
                self.milestone_usd - self.spent_before - self.spent_now,
            ),
        )


def ledger_path() -> Path:
    return RESULTS / MILESTONE / "ledger.json"


def read_ledger() -> dict[str, Any]:
    p = ledger_path()
    if not p.is_file():
        return {"milestone": MILESTONE, "runs": []}
    data: dict[str, Any] = json.loads(p.read_text())
    return data


def write_ledger(data: dict[str, Any]) -> None:
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def check_configuration(config: ConfigService, me: Principal, deepen: bool = False) -> Path:
    """The corpus folder, or ``GateStop("G1")`` with the commands that fix the setup."""
    from mosaic.ai.registry import adapter_for

    problems: list[str] = []
    commands: list[str] = []
    corpus = str(config.get(me, "eval.corpus_dir") or "")
    if not corpus:
        problems.append("the eval corpus folder is not set")
        commands.append(
            "mosaic config set eval.corpus_dir /path/to/corpus  # a folder of trip folders"
        )
    for cap in ("vision", "planner", "selector", *(("reviewer",) if deepen else ())):
        choice = config.provider(me, cap)
        if choice.provider == "fake":
            problems.append(f"{cap} uses the offline fake provider; the eval needs a real one")
            commands.append(
                "mosaic config ai use claude-cli   # or codex-cli, or anthropic + set-key"
            )
            continue
        try:
            adapter_for(config, me, choice.provider)
        except NotConfiguredError as exc:
            problems.append(f"{cap} ({choice.provider}): {exc}")
            if choice.provider == "anthropic":
                commands.append(
                    "mosaic config ai set-key --provider anthropic   # or, with no API key: "
                    "mosaic config ai use claude-cli  (or codex-cli)"
                )
            else:
                commands.append(
                    "mosaic config ai use claude-cli   # uses the installed Claude Code sign-in"
                )
    if problems:
        lines = ["not configured:", *(f"  - {p}" for p in problems), "run:"]
        lines += [f"  {c}" for c in dict.fromkeys(commands)]
        lines.append("then: mosaic config ai test   and   make eval")
        raise GateStop("G1", "\n".join(lines))
    path = Path(corpus).expanduser()
    if not path.is_dir():
        raise GateStop("G1", f"eval.corpus_dir {path} is not a folder")
    return path


def trips(corpus: Path) -> list[Path]:
    """Trip folders: direct subfolders that contain video (or the corpus folder itself)."""

    def has_video(folder: Path) -> bool:
        return any(
            p.suffix.lower() in VIDEO_EXT
            for p in folder.rglob("*")
            if p.is_file() and "MosAic" not in p.relative_to(folder).parts
        )

    subs = sorted(p for p in corpus.iterdir() if p.is_dir() and not p.name.startswith("."))
    found = [p for p in subs if p.name != "MosAic" and has_video(p)]
    return found or ([corpus] if has_video(corpus) else [])


class _Paused(Exception):  # noqa: N818 - internal control flow
    pass


def _wait(control: ControlDB, job_id: int, label: str) -> str:
    """Follow a job to its end; a job paused at its cost limit returns
    ``"paused_cost_limit"`` (that state is not terminal: it would wait forever)."""

    def show(p: JobProgress) -> None:
        item = f" — {p.current_item}" if p.current_item else ""
        print(f"  [{label} {p.pct:3d}%] {p.stage or p.status} {p.done}/{p.total}{item}", flush=True)
        if p.status == "paused_cost_limit":
            raise _Paused

    proc = ensure_worker(control)
    try:
        prog = wait_for_job(JobStore(control.db), job_id, show, control=control, worker=proc)
    except _Paused:
        return "paused_cost_limit"
    return prog.status


def _run_job(control: ControlDB, job_id: int, label: str, budget: Budget, trip: str) -> None:
    """Wait for a job and always count its spend; a budget pause stops at gate G2."""
    status = "failed"
    try:
        status = _wait(control, job_id, label)
        if status == "paused_cost_limit":
            JobStore(control.db).cancel(job_id)  # before reading its final cost
    finally:
        budget.spent_now += _job_cost(control, job_id)
    if status == "paused_cost_limit":
        raise GateStop(
            "G2",
            f"{trip}: {label} reached the eval budget (run ${budget.run_usd:.2f}, milestone "
            f"${budget.milestone_usd:.2f}); the job was cancelled and its cached results are "
            "kept. Raise ai.budget.per_eval_run_usd / per_milestone_usd only with the "
            "owner's approval.",
        )
    if status != "done":
        raise RuntimeError(f"{trip}: {label} {status}")


def _job_cost(control: ControlDB, job_id: int) -> float:
    job = JobStore(control.db).job(job_id)
    return float(job.cost_usd or 0.0) if job else 0.0


def run_trip(
    control: ControlDB,
    me: Principal,
    trip: Path,
    budget: Budget,
    render: bool,
    deepen: bool = False,
) -> dict[str, Any]:
    from mosaic.editing.service import create_edit, get_version, submit_generate
    from mosaic.media.pipeline import submit_analysis
    from mosaic.render.service import create_render, get_render, submit_render
    from mosaic.render.tasks import output_path
    from mosaic.storage.projects import NotAProjectError, init_project, open_project

    executor = LocalExecutor(JobStore(control.db))
    name = trip.name
    print(f"== {name}", flush=True)
    try:
        project = open_project(control, me, trip)
    except NotAProjectError:
        project = init_project(control, me, trip)
    result: dict[str, Any] = {"trip": name, "started_at": now_iso()}
    try:
        if budget.remaining <= 0:
            raise GateStop("G2", "the eval budget is used up for this run or milestone")
        job = submit_analysis(executor, me, project, cost_limit_usd=budget.remaining)
        _run_job(control, job, "analysis", budget, name)
        # Context first: the L3 review prompt includes it.
        apply_context(project, CORPUS_META / name.lower() / "context.json")
        if deepen:
            from mosaic.library.review import submit_deepen

            if budget.remaining <= 0:
                raise GateStop("G2", "the eval budget is used up for this run or milestone")
            deep = submit_deepen(executor, me, project, cost_limit_usd=budget.remaining)
            deep_job, count = deep.job, deep.candidates
            print(f"  deep review of {count} candidates", flush=True)
            if deep_job is not None:
                _run_job(control, deep_job, "deep review", budget, name)
                check_deep_review(control, deep_job, name)
            result["deep_review_candidates"] = count

        meta = CORPUS_META / name.lower() / "expectations.yaml"
        expect = exp.load(meta)
        if expect is None:
            with project.db.session() as s:
                expect = exp.draft(s, name)
            exp.save(meta, expect)
            shown = meta.relative_to(REPO) if meta.is_relative_to(REPO) else meta
            print(f"  drafted {shown} (draft: true)", flush=True)

        spec = DEFAULT_EDIT | TRIP_EDITS.get(name.lower(), {}) | expect.get("edit", {})
        request = EditRequest.model_validate(spec)
        edit_id = create_edit(project, request, control, me)
        if budget.remaining <= 0:
            raise GateStop("G2", "the eval budget is used up for this run or milestone")
        job = submit_generate(executor, me, project, edit_id, cost_limit_usd=budget.remaining)
        _run_job(control, job, "edit", budget, name)
        v = get_version(project, edit_id)
        events = v.timeline["tracks"][0]["events"]
        result |= {
            "edit": f"edt_{edit_id:04d}",
            "version": v.version,
            "request": v.request,
            "rate": v.rate,
            "metrics": v.metrics,
            "findings": v.findings,
            "expectations": exp.score(expect, events, _files(project)),
            "subject_shares": exp.subject_shares(
                expect, events, _primary_subjects(project, events)
            ),
        }
        if render:
            rid = create_render(project, edit_id, v.version, "final")
            job = submit_render(executor, me, project, rid)
            _run_job(control, job, "render", budget, name)
            r = get_render(project, rid)
            assert r is not None
            result["render"] = {
                "path": str(output_path(project.workspace, r)),
                "metrics": r.metrics,
            }
    finally:
        project.close()
    result["finished_at"] = now_iso()
    return result


def check_deep_review(control: ControlDB, job_id: int, trip: str) -> None:
    """A deep review whose tasks were skipped must never look like a finished one."""
    skipped = [
        t.error or "no reason recorded"
        for t in JobStore(control.db).tasks(job_id)
        if t.kind == "library.review" and t.status == "skipped"
    ]
    if skipped:
        raise GateStop("G1", f"{trip}: deep review skipped ({len(skipped)} tasks): {skipped[0]}")


def apply_context(project: Any, path: Path) -> None:
    """The trip's context from the repo (owner-provided facts), if any."""
    from mosaic.library.context import TripContext, load, save

    # No file means no context: clear any left from an earlier run (reproducible evals).
    ctx = (
        TripContext.model_validate(json.loads(path.read_text()))
        if path.is_file()
        else TripContext()
    )
    with project.write() as s:
        if load(s).digest() != ctx.digest():
            save(s, ctx, "user")
            print(f"  trip context: {path.name if path.is_file() else 'cleared'}", flush=True)


def _primary_subjects(project: Any, events: list[dict[str, Any]]) -> dict[str, str]:
    """Each used clip's primary subject: the first subject of the L3 review (ordered most
    important first, context-aware) when present, else of the L2 vision observation.
    Descriptions mention everything in frame ("spectators photograph a distant jet"), so
    they over-count; the primary subject says what the clip is about."""
    from sqlalchemy import select

    from mosaic.storage.models_project import DeepReview, VisualObservation

    ids = [int(e["segment_id"][4:]) for e in events]
    out: dict[str, str] = {}
    with project.db.session() as s:
        for model in (VisualObservation, DeepReview):  # L3 overwrites L2
            for sid, data in s.execute(
                select(model.segment_id, model.data).where(model.segment_id.in_(ids))
            ):
                subjects = data.get("subjects") or [""]
                out[f"seg_{sid:06d}"] = str(subjects[0])
    return out


def _files(project: Any) -> dict[str, int]:
    with project.db.session() as s:
        return exp.file_assets(s)


def write_results(result: dict[str, Any]) -> Path:
    out = RESULTS / MILESTONE / f"{result['trip'].lower()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    md = out.with_suffix(".md")
    if not md.exists():  # the rubric is the owner's to fill in; never overwrite scores
        template = (REPO / "tests" / "evaluation" / "rubric.template.md").read_text()
        md.write_text(template.replace("{{trip}}", result["trip"]))
    return out


def blocking_ok(result: dict[str, Any]) -> bool:
    m = result.get("metrics", {})
    ok = bool(m.get("blocking_ok"))
    score = result.get("expectations", {})
    if score and not score.get("draft", True) and score.get("must_exclude_violations"):
        ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="make eval")
    ap.add_argument("--trip", action="append", help="only this trip folder name (repeatable)")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--deepen", action="store_true", help="run the L3 deep review (Thorough)")
    args = ap.parse_args(argv)
    control = ControlDB()
    me = control.local_principal
    config = ConfigService(control)
    try:
        corpus = check_configuration(config, me, deepen=args.deepen)
        ledger = read_ledger()
        budget = Budget(
            float(config.get(me, "ai.budget.per_eval_run_usd")),
            float(config.get(me, "ai.budget.per_milestone_usd")),
            sum(float(r.get("cost_usd", 0.0)) for r in ledger["runs"]),
        )
        selected = [t for t in trips(corpus) if not args.trip or t.name in args.trip]
        if not selected:
            raise GateStop("G1", f"no trip folders with video under {corpus}")
        results = []
        ok = True
        try:
            for trip in selected:
                res = run_trip(
                    control, me, trip, budget, render=not args.no_render, deepen=args.deepen
                )
                write_results(res)
                results.append(res)
                ok = ok and blocking_ok(res)
                m = res["metrics"]
                print(
                    f"  {res['trip']}: {m['events']} events, error {m['duration_error_frames']:+d} "
                    f"frames, blocking {'ok' if blocking_ok(res) else 'FAILED'}",
                    flush=True,
                )
        finally:
            ledger["runs"].append(
                {
                    "at": now_iso(),
                    "trips": [r["trip"] for r in results],
                    "cost_usd": round(budget.spent_now, 6),
                }
            )
            write_ledger(ledger)
        milestone = budget.spent_before + budget.spent_now
        print(f"eval cost ${budget.spent_now:.4f} (milestone ${milestone:.4f})")
        return 0 if ok else 1
    except GateStop as stop:
        print(str(stop), file=sys.stderr)
        return EXIT_GATE
    finally:
        control.db.dispose()


if __name__ == "__main__":
    sys.exit(main())
