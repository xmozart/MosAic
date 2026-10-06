"""``mosaic``: the user-facing CLI. Thin wrappers over the same services as the API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import click

from mosaic.cli.config_cmd import config as config_group
from mosaic.storage.control import ControlDB
from mosaic.storage.lease import LeaseHeldError
from mosaic.storage.placement import PlacementRefusedError
from mosaic.storage.projects import Project, ProjectBusyError, SnapshotConflictError


@click.group()
@click.version_option(package_name="mosaic")
def cli() -> None:
    """MosAic: turn a folder of trip footage into story-driven edits."""


def _control() -> ControlDB:
    return ControlDB()


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--name", default=None, help="Project name (default: folder name).")
@click.option(
    "--placement",
    type=click.Choice(["in_folder", "split", "external"]),
    default=None,
    help="Override where project data lives (default: chosen from the folder's storage); "
    "an existing project is moved.",
)
def init(folder: Path, name: str | None, placement: str | None) -> None:
    """Create a project for FOLDER. Original footage is never modified."""
    from mosaic.storage.placement import Placement
    from mosaic.storage.projects import init_project

    control = _control()
    try:
        project = init_project(
            control,
            control.local_principal,
            folder,
            name,
            Placement(placement) if placement else None,
        )
        click.echo(f"Project {project.descriptor.name} ({project.id})")
        click.echo(f"Placement: {project.placement.value}")
        click.echo(f"  live database and cache: {project.live_dir}")
        click.echo(f"  edits, renders and snapshots: {project.outputs_dir}")
        click.echo("Original footage stays where it is and will not be modified.")
        project.close()
    except (
        PlacementRefusedError,
        ProjectBusyError,
        SnapshotConflictError,
        LeaseHeldError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        control.db.dispose()


@cli.command()
@click.option("--port", default=8765, show_default=True)
def serve(port: int) -> None:
    """Run the local API on 127.0.0.1 (M0: no auth, loopback only)."""
    from mosaic.app.main import serve as run_server

    run_server(port)


@cli.command()
@click.option("--exit-when-idle", type=float, default=None)
def worker(exit_when_idle: float | None) -> None:
    """Run a worker process (normally started automatically)."""
    from mosaic.jobs.worker import main

    main(["--exit-when-idle", str(exit_when_idle)] if exit_when_idle is not None else [])


def _open(control: ControlDB, folder: Path, *, read_only: bool = False) -> Project:
    """Open a project: for editing (takes the lease; ADR 0023) or ``read_only``."""
    from mosaic.storage.projects import NotAProjectError, open_project

    try:
        return open_project(control, control.local_principal, folder, read_only=read_only)
    except LeaseHeldError as exc:
        raise click.ClickException(
            f"{exc}\nRead-only commands still work; `mosaic lock {folder} --take-over` takes "
            "it over."
        ) from exc
    except (
        NotAProjectError,
        PlacementRefusedError,
        ProjectBusyError,
        SnapshotConflictError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc


def _follow(control: ControlDB, job_id: int) -> str:
    from mosaic.jobs.client import ensure_worker, wait_for_job
    from mosaic.jobs.model import JobProgress
    from mosaic.jobs.store import JobStore

    def show(p: JobProgress) -> None:
        item = f" — {p.current_item}" if p.current_item else ""
        click.echo(f"  [{p.pct:3d}%] {p.stage or p.status} {p.done}/{p.total}{item}")
        if p.status == "paused_cost_limit":  # not terminal: stop following, explain
            raise click.ClickException(
                f"job {p.job_id} paused at its AI cost limit (${p.cost_usd:.2f}). To continue, "
                "raise `mosaic config set ai.budget.per_job_usd <usd>` and run the command "
                "again: finished work and AI answers are reused. The paused job stays queued "
                "until then."
            )

    proc = ensure_worker(control)
    prog = wait_for_job(JobStore(control.db), job_id, show, control=control, worker=proc)
    return prog.status


def _overrides(pairs: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise click.ClickException(f"--set needs KEY=VALUE, got {pair!r}")
        key = key.strip()
        if key == "tiles":
            cols, _, rows = value.lower().partition("x")
            out[key] = (int(cols), int(rows)) if rows else value
        elif key in ("l2", "l3"):
            out[key] = value.lower() in ("1", "true", "yes", "on")
        else:
            out[key] = value
    return out


def _show_estimate(control: Any, project: Any, config: Any) -> None:
    from mosaic.library.estimate import for_project
    from mosaic.storage.config import ConfigService

    with project.db.session() as s:
        est = for_project(s, ConfigService(control), control.local_principal, config)
    if not est.videos:
        click.echo("No probed footage yet: run an analysis (or a scan) first.")
        return
    lo, hi = est.wall_seconds
    cost = (
        "AI cost unknown (no price for a configured model)"
        if est.cost_usd is None
        else f"AI ${est.cost_usd[0]:.2f}–{est.cost_usd[1]:.2f}"
    )
    click.echo(
        f"{config.name}: {est.videos} videos, {est.video_seconds // 60} min of footage, "
        f"{est.photos} photos"
    )
    click.echo(
        f"  about {lo // 60}–{-(-hi // 60)} min · {cost} · "
        f"{est.storage_bytes / 1e9:.1f} GB · {est.l2_calls} sheets"
        + (f" · {est.l3_calls[0]}–{est.l3_calls[1]} deep reviews" if config.l3 else "")
    )
    if est.basis == "default":
        click.echo(
            "  (time from typical speeds; `mosaic hardware FOLDER --benchmark` measures "
            "this computer)"
        )


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--mode",
    type=click.Choice(["quick", "balanced", "thorough", "custom"]),
    default="balanced",
    show_default=True,
    help="Analysis depth (docs/ANALYSIS_MODES.md).",
)
@click.option(
    "--set",
    "overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help="Custom mode parameter, e.g. sample_interval=2 or tiles=5x4 (repeatable).",
)
@click.option("--estimate", is_flag=True, help="Show the estimate and exit.")
def analyze(folder: Path, mode: str, overrides: tuple[str, ...], estimate: bool) -> None:
    """Analyze FOLDER's footage into the project library."""
    from pydantic import ValidationError

    from mosaic.core.modes import UnknownModeError, resolve
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import needs_benchmark, submit_analysis

    try:
        config = resolve(mode, _overrides(overrides) or None)
    except (UnknownModeError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    control = _control()
    project = _open(control, folder, read_only=estimate)
    try:
        if estimate:
            _show_estimate(control, project, config)
            return
        job_id = submit_analysis(
            LocalExecutor(JobStore(control.db)),
            control.local_principal,
            project,
            config,
            benchmark=needs_benchmark(control),
        )
        click.echo(f"Analysis job {job_id} ({mode})")
        status = _follow(control, job_id)
    finally:
        project.close()
        control.db.dispose()
    if status != "done":
        raise click.ClickException(f"analysis {status}; see `mosaic-dev inspect {folder}`")
    click.echo("Analysis complete.")


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--duration", type=int, required=True, help="Target length in seconds.")
@click.option("--story", default="cinematic_journey", show_default=True)
@click.option(
    "--chronology",
    type=click.Choice(["strict", "mostly", "thematic", "story"]),
    default="mostly",
    show_default=True,
)
@click.option(
    "--pace",
    type=click.Choice(["very_slow", "slow", "balanced", "energetic", "fast", "very_fast"]),
    default="balanced",
    show_default=True,
)
@click.option("--instructions", default="", help="Free-text instructions for the editor.")
@click.option("--fps", default=None, help="Timeline rate, e.g. 29.97 (default: dominant source).")
@click.option("--variant", type=int, default=0, help="A different take of the same request.")
def edit(
    folder: Path,
    duration: int,
    story: str,
    chronology: str,
    pace: str,
    instructions: str,
    fps: str | None,
    variant: int,
) -> None:
    """Generate an edit of FOLDER's analyzed footage."""
    from pydantic import ValidationError

    from mosaic.editing.request import EditRequest
    from mosaic.editing.service import (
        create_edit,
        edit_ref,
        get_version,
        report,
        report_text,
        submit_generate,
    )
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore

    try:
        request = EditRequest(
            duration_s=duration,
            story=story,
            chronology=chronology,
            pace=pace,
            instructions=instructions,
            fps=fps,
            variant=variant,
        )
    except ValidationError as exc:
        msgs = "; ".join(e["msg"] for e in exc.errors())
        raise click.ClickException(msgs) from None
    control = _control()
    project = _open(control, folder)
    try:
        edit_id = create_edit(project, request, control, control.local_principal)
        store = JobStore(control.db)
        job_id = submit_generate(LocalExecutor(store), control.local_principal, project, edit_id)
        click.echo(f"Edit {edit_ref(edit_id)} — job {job_id}")
        status = _follow(control, job_id)
        if status != "done":
            failed = [t.error for t in store.tasks(job_id) if t.status == "failed"]
            detail = f": {failed[0].splitlines()[0]}" if failed and failed[0] else ""
            raise click.ClickException(f"edit {status}{detail}")
        v = get_version(project, edit_id)
        click.echo(report_text(report(project, edit_id, v.version)).split("\n\n", 1)[0])
        click.echo(
            f"Saved {edit_ref(edit_id)} v{v.version}. "
            f"Details: mosaic report {folder} {edit_ref(edit_id)}"
        )
    finally:
        project.close()
        control.db.dispose()


@cli.command()
@click.argument(
    "folder", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("--benchmark", is_flag=True, help="Measure this computer (runs in FOLDER's queue).")
@click.option("--force", is_flag=True, help="Measure again even if a result exists.")
def hardware(folder: Path | None, benchmark: bool, force: bool) -> None:
    """Show this computer's hardware, worker slots and measured speed (ADR 0030)."""
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.jobs.worker import configured_slots
    from mosaic.media import benchmark as bench_mod
    from mosaic.media import hardware as hw_mod
    from mosaic.media.pipeline import submit_benchmark

    control = _control()
    try:
        if benchmark:
            if folder is None:
                raise click.ClickException("--benchmark needs a project FOLDER for its job")
            project = _open(control, folder)
            try:
                job_id = submit_benchmark(
                    LocalExecutor(JobStore(control.db)), control.local_principal, project, force
                )
                status = _follow(control, job_id)
            finally:
                project.close()
            if status != "done":
                raise click.ClickException(f"benchmark {status}")
        hw = hw_mod.probe()
        mem = f"{hw.memory_bytes / (1 << 30):.0f} GB" if hw.memory_bytes else "memory unknown"
        cores = f"{hw.cpu_logical} threads"
        if hw.cpu_performance:
            cores += f", {hw.cpu_performance} performance cores"
        click.echo(f"{hw.cpu_model or hw.arch} · {cores} · {mem}")
        click.echo(f"  hardware encoders: {', '.join(hw.hw_encoders) or 'none (software)'}")
        slots = configured_slots(control)
        click.echo("  worker slots: " + ", ".join(f"{k} {v}" for k, v in slots.items()))
        found = bench_mod.latest(control, hw)
        if found is None:
            click.echo("  not measured yet: the first analysis measures it, or use --benchmark")
            return
        per = found.result["ms_per_minute"]
        embed = found.embed_ms
        click.echo(
            "  per minute of 4K footage: "
            f"540p proxy {per['lrf_or_540'] / 1000:.1f} s, 720p proxy {per['720'] / 1000:.1f} s, "
            f"frame analysis {per['analysis'] / 1000:.1f} s"
            + (f"; {embed} ms per image embedding" if embed is not None else "")
        )
        click.echo(f"  measured {found.created_at}")
    finally:
        control.db.dispose()


@cli.command(name="report")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("edit_id")
@click.option("--version", "version", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, help="Print the full JSON report.")
def report_cmd(folder: Path, edit_id: str, version: int | None, as_json: bool) -> None:
    """Selection and rejection report with metrics for EDIT_ID (edt_0001 or its id)."""
    import json

    from mosaic.editing.service import EditNotFoundError, report, report_text, resolve_edit

    control = _control()
    project = _open(control, folder, read_only=True)
    try:
        r = report(project, resolve_edit(project, edit_id), version)
    except EditNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        project.close()
        control.db.dispose()
    click.echo(json.dumps(r, indent=2, ensure_ascii=False) if as_json else report_text(r))


@cli.command(name="render")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("edit_id", required=False)
@click.option("--version", "version", type=int, default=None, help="Default: latest.")
@click.option("--final", is_flag=True, help="1080p from the original files (default: preview).")
@click.option("--lossless", is_flag=True, hidden=True, help="FFV1/PCM Matroska (tests).")
def render_cmd(
    folder: Path, edit_id: str | None, version: int | None, final: bool, lossless: bool
) -> None:
    """Render an edit (default: the most recent edit, latest version, preview)."""
    from sqlalchemy import select

    from mosaic.editing.service import EditNotFoundError, edit_ref, resolve_edit
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.render.service import create_render, get_render, latest_version, submit_render
    from mosaic.render.tasks import output_path
    from mosaic.storage.models_project import Edit

    control = _control()
    project = _open(control, folder)
    try:
        if edit_id:
            eid = resolve_edit(project, edit_id)
        else:
            with project.db.session() as s:
                found = s.scalar(select(Edit.id).order_by(Edit.id.desc()).limit(1))
            if found is None:
                raise EditNotFoundError("no edits yet; run `mosaic edit` first")
            eid = found
        v = version or latest_version(project, eid)
        if v is None:
            raise EditNotFoundError(f"{edit_ref(eid)} has no versions yet")
        kind = "final" if final else "preview"
        rid = create_render(project, eid, v, kind, lossless)
        job_id = submit_render(
            LocalExecutor(JobStore(control.db)), control.local_principal, project, rid
        )
        click.echo(f"Render {edit_ref(eid)} v{v} ({kind}) — job {job_id}")
        status = _follow(control, job_id)
        r = get_render(project, rid)
        if status != "done" or r is None or r.status != "done":
            failed = [t.error for t in JobStore(control.db).tasks(job_id) if t.status == "failed"]
            detail = f": {failed[0].splitlines()[0]}" if failed and failed[0] else ""
            raise click.ClickException(f"render {status}{detail}")
        m = r.metrics
        click.echo(
            f"Saved {output_path(project.workspace, r)} — {m['frames']} frames at {m['rate']}, "
            f"{m['loudness_lufs']} LUFS, true peak {m['true_peak_dbtp']} dBTP"
        )
    except (EditNotFoundError, LookupError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        project.close()
        control.db.dispose()


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--day", "days", type=int, multiple=True, help="Only this trip day (1 = first); repeatable."
)
@click.option("--segment", "segments", multiple=True, help="Only these segments (seg_000123).")
@click.option(
    "--target",
    type=click.Choice(["thorough", "balanced"]),
    default="thorough",
    show_default=True,
    help="balanced adds only missing L2; thorough also reviews candidates (L3).",
)
def deepen(folder: Path, days: tuple[int, ...], segments: tuple[str, ...], target: str) -> None:
    """Deepen analysis of the trip, some days or some clips; earlier work is reused."""
    from mosaic.editing.retrieval import parse_ref
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.library.review import DeepenScope, submit_deepen

    ids = []
    for ref in segments:
        sid = parse_ref(ref)
        if sid is None:
            raise click.ClickException(f"not a segment id: {ref}")
        ids.append(sid)
    control = _control()
    project = _open(control, folder)
    try:
        run = submit_deepen(
            LocalExecutor(JobStore(control.db)),
            control.local_principal,
            project,
            DeepenScope(days, tuple(ids)),
            target=target,
        )
        if run.dropped:
            click.echo(
                "Not candidates (rejected, a non-recommended look-alike, or unknown): "
                + ", ".join(f"seg_{i:06d}" for i in run.dropped)
            )
        if run.job is None:
            click.echo("Nothing to add in this scope.")
            return
        if run.l2_assets:
            click.echo(f"Scene understanding (L2) first for {len(run.l2_assets)} clips")
        if target == "thorough":
            click.echo(f"Deep review of {run.candidates} candidate clips")
        click.echo(f"Job {run.job}")
        status = _follow(control, run.job)
    finally:
        project.close()
        control.db.dispose()
    if status != "done":
        raise click.ClickException(f"deepen {status}")
    click.echo("Deepening complete. New edits use it; regenerate an edit to apply it.")


@cli.group()
def jobs() -> None:
    """Background jobs."""


@jobs.command("resume")
@click.argument("job_id", type=int)
@click.option("--cost-limit", type=float, default=None, help="New AI cost limit in USD.")
def jobs_resume(job_id: int, cost_limit: float | None) -> None:
    """Resume a paused job, optionally raising its AI cost limit first."""
    from mosaic.core.principal import check
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore

    control = _control()
    try:
        store = JobStore(control.db)
        job = store.job(job_id)
        if job is None:
            raise click.ClickException(f"no job {job_id}")
        # Equal to the spend would pause again at the next reservation.
        if cost_limit is not None and (cost_limit < 0 or cost_limit <= (job.cost_usd or 0)):
            raise click.ClickException(
                f"the job has already spent ${job.cost_usd:.2f}; the limit must be higher"
            )
        executor = LocalExecutor(store)
        check(control.local_principal, "job.resume", str(job_id))
        if cost_limit is not None:
            store.set_cost_limit(job_id, cost_limit)
        executor.resume(control.local_principal, job_id)
        click.echo(f"Job {job_id} resumed")
        status = _follow(control, job_id)
    finally:
        control.db.dispose()
    if status != "done":
        raise click.ClickException(f"job {status}")


@cli.group()
def context() -> None:
    """Trip context: what the trip is about (optional; improves stories and titles)."""


def _save_context(folder: Path, data: object, source: Literal["user", "ai_parsed"]) -> int:
    from pydantic import ValidationError

    from mosaic.library.context import TripContext, save

    try:
        ctx = TripContext.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise click.ClickException(f"invalid trip context: {msgs}") from None
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.library.summaries import submit_summaries

    control = _control()
    project = _open(control, folder)
    try:
        with project.write() as s:
            rev = save(s, ctx, source)
        # A context change re-runs summaries only (PRODUCT.md §3).
        job = submit_summaries(
            LocalExecutor(JobStore(control.db)), control.local_principal, project
        )
        click.echo(f"Refreshing summaries with the new context (job {job})")
        _follow(control, job)
        return rev
    finally:
        project.close()
        control.db.dispose()


@context.command("show")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def context_show(folder: Path) -> None:
    """Print the project's trip context as JSON."""
    import json

    from mosaic.library.context import load

    control = _control()
    project = _open(control, folder, read_only=True)
    try:
        with project.db.session() as s:
            click.echo(json.dumps(load(s).model_dump(mode="json"), indent=2, ensure_ascii=False))
    finally:
        project.close()
        control.db.dispose()


@context.command("set")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--file", "file_", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True
)
def context_set(folder: Path, file_: Path) -> None:
    """Set the trip context from a JSON file (PRODUCT.md §3 structure)."""
    import json

    try:
        data = json.loads(file_.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{file_}: not valid JSON ({exc.msg})") from None
    rev = _save_context(folder, data, "user")
    click.echo(f"Trip context saved (revision {rev}). Edits made from now on use it.")


@context.command("parse")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--text", default=None, help="Notes or itinerary (or use --file).")
@click.option("--file", "file_", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True, help="Save the proposal without asking.")
def context_parse(folder: Path, text: str | None, file_: Path | None, yes: bool) -> None:
    """Turn free-text notes into a trip context with AI, show it, and save it if confirmed."""
    import json

    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
    from mosaic.jobs.store import JobStore

    notes = file_.read_text() if file_ else text
    if not notes or not notes.strip():
        raise click.ClickException("give the notes with --text or --file")
    control = _control()
    project = _open(control, folder)
    try:
        store = JobStore(control.db)
        job = LocalExecutor(store).submit(
            control.local_principal,
            JobSpec(
                project_id=project.id,
                kind="context",
                tasks=[
                    TaskSpec(
                        kind="context.parse",
                        stage="context",
                        resource_class=ResourceClass.AI_API,
                        params={"text": notes},
                        label="reading the trip notes",
                    )
                ],
            ),
        )
        status = _follow(control, job)
        tasks = store.tasks(job)
        if status != "done" or not tasks or not tasks[0].result:
            detail = (tasks[0].error or "").splitlines()[0] if tasks and tasks[0].error else status
            raise click.ClickException(f"could not read the notes: {detail}")
        proposal = tasks[0].result["proposal"]
    finally:
        project.close()
        control.db.dispose()
    click.echo(json.dumps(proposal, indent=2, ensure_ascii=False))
    if not yes and not click.confirm("Save this trip context?", default=True):
        click.echo("Not saved.")
        return
    rev = _save_context(folder, proposal, "ai_parsed")
    click.echo(f"Trip context saved (revision {rev}).")


@context.command("clear")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def context_clear(folder: Path) -> None:
    """Remove the trip context (edits then work without it)."""
    rev = _save_context(folder, {}, "user")
    click.echo(f"Trip context cleared (revision {rev}).")


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--take-over", is_flag=True, help="Take the project over from another computer.")
@click.option("--release", is_flag=True, help="Release this computer's lease.")
def lock(folder: Path, take_over: bool, release: bool) -> None:
    """Show who holds FOLDER's project for editing; take it over or release it."""
    from mosaic.storage import lease
    from mosaic.storage.projects import open_project

    control = _control()
    try:
        project = _open(control, folder, read_only=True)
        out = project.outputs_dir
        project.close(checkpoint=False)
        held = lease.read(out)
        mine = held is not None and held.holder == control.installation_id
        if release:
            lease.release(out, control.installation_id)
            click.echo("Released." if mine else "This computer did not hold the project.")
            return
        if take_over:
            if held and not mine and not held.expired():
                click.confirm(
                    f"{held.host} is editing this project (lease until {held.expires_at}). "
                    "Take it over? It loses edit access.",
                    abort=True,
                )
            p = open_project(control, control.local_principal, folder, take_over=True)
            p.close(checkpoint=False)
            click.echo("This computer now holds the project.")
            return
        if held is None or held.expired():
            click.echo("Nobody is editing this project.")
        else:
            who = "this computer" if mine else held.host
            click.echo(f"Held by {who} since {held.acquired_at} (until {held.expires_at}).")
    finally:
        control.db.dispose()


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--level",
    type=click.Choice(["trip", "day", "scene", "shot"]),
    default="day",
    show_default=True,
    help="day prints the trip summary, then each day.",
)
def summary(folder: Path, level: str) -> None:
    """Print the trip's summaries (written during analysis)."""
    from sqlalchemy import select

    from mosaic.storage.models_project import Summary

    levels = ["trip", "day"] if level == "day" else [level]
    control = _control()
    project = _open(control, folder, read_only=True)
    printed = 0
    try:
        with project.db.session() as s:
            q = (
                select(Summary)
                .where(Summary.level.in_(levels))
                .order_by(Summary.level.desc(), Summary.ref)
                .execution_options(yield_per=500)  # shots can number tens of thousands
            )
            for r in s.scalars(q):
                printed += 1
                _print_summary(r)
    finally:
        project.close()
        control.db.dispose()
    if not printed:
        click.echo("No summaries yet: run an analysis first.")


def _print_summary(r: Any) -> None:
    if r.level == "trip":
        name = "Trip"
    elif r.level == "day":
        name = f"Day {r.ref}" if r.ref else "Undated"
    else:
        name = f"{r.level} {r.ref}"
    themes = ", ".join(r.data.get("themes", []))
    click.echo(f"{name}: {r.text}" + (f"\n  themes: {themes}" if themes else ""))
    if r.data.get("highlights"):
        click.echo(f"  highlights: {', '.join(r.data['highlights'])}")


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--set",
    "sets",
    multiple=True,
    metavar="DEVICE=OFFSET",
    help="Set a device's clock offset, e.g. 2=+5h or 3=-00:30:00 (added to its times).",
)
@click.option("--accept", "accepts", multiple=True, type=int, help="Accept a suggestion.")
def clock(folder: Path, sets: tuple[str, ...], accepts: tuple[int, ...]) -> None:
    """Show each device's clock offset and suggestion; set or accept offsets."""
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.library.devices import (
        device_rows,
        format_offset,
        parse_offset,
        set_offset,
        submit_time_refresh,
    )
    from mosaic.storage.models_project import DeviceSuggestion

    control = _control()
    writing = bool(sets or accepts)
    project = _open(control, folder, read_only=not writing)
    try:
        if writing:
            changed = 0
            with project.write() as s:
                for item in sets:
                    dev, _, value = item.partition("=")
                    try:
                        changed += set_offset(s, int(dev), parse_offset(value), "user")
                    except (ValueError, LookupError) as exc:
                        raise click.ClickException(str(exc)) from exc
                for dev_id in accepts:
                    sg = s.get(DeviceSuggestion, dev_id)
                    if sg is None:
                        raise click.ClickException(f"device {dev_id} has no suggestion")
                    changed += set_offset(s, dev_id, sg.offset_ms, "accepted", sg.utc_offset_min)
            click.echo(f"Corrected the capture times of {changed} clips and photos.")
            job = submit_time_refresh(
                LocalExecutor(JobStore(control.db)), control.local_principal, project
            )
            _follow(control, job)
        with project.db.session() as s:
            rows = device_rows(s)
    finally:
        project.close()
        control.db.dispose()
    if not rows:
        click.echo("No devices yet: run an analysis (or a scan) to list the cameras.")
    for r in rows:
        source = f" [{r['offset_source']}]" if r["offset_source"] != "none" else ""
        offset = format_offset(r["clock_offset_ms"])
        click.echo(f"{r['id']:>3}  {r['label']} ({r['assets']} items)  offset {offset}{source}")
        sg = r["suggestion"]
        if sg and not sg["applied"]:
            click.echo(
                f"     suggestion: appears {sg['verdict']} ({sg['pairs']} matching pairs); "
                f"accept with --accept {r['id']}"
            )


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--lut", "luts", multiple=True, metavar="DEVICE=PATH", help="Assign a .cube LUT.")
@click.option("--clear-lut", "clears", multiple=True, type=int, help="Remove a device's LUT.")
def device(folder: Path, luts: tuple[str, ...], clears: tuple[int, ...]) -> None:
    """Assign LUTs to devices that record log footage (Apple Log, N-Log, D-Log M…)."""
    from mosaic.library.devices import device_rows, set_lut
    from mosaic.media.lut import LutError

    control = _control()
    writing = bool(luts or clears)
    project = _open(control, folder, read_only=not writing)
    try:
        for item in luts:
            dev, _, path = item.partition("=")
            try:
                set_lut(project, int(dev), path)
            except (ValueError, LookupError, LutError) as exc:
                raise click.ClickException(str(exc)) from exc
        for dev_id in clears:
            try:
                set_lut(project, dev_id, None)
            except LookupError as exc:
                raise click.ClickException(str(exc)) from exc
        with project.db.session() as s:
            rows = device_rows(s)
    finally:
        project.close()
        control.db.dispose()
    for r in rows:
        lut = r["lut_path"] or "no LUT"
        click.echo(f"{r['id']:>3}  {r['label']} ({r['assets']} items)  {lut}")
    if writing:
        click.echo(f"Run `mosaic analyze {folder}` to apply it to previews and analysis.")


@cli.command(name="search")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("query")
@click.option("--mode", type=click.Choice(["all", "visual", "speech"]), default="all")
@click.option("--limit", type=int, default=20, show_default=True)
def search_cmd(folder: Path, query: str, mode: str, limit: int) -> None:
    """Search the library by what clips show or what was said."""
    from mosaic.ai.registry import embedder
    from mosaic.core.time import format_display, parse_rational
    from mosaic.library import search as lib
    from mosaic.storage.config import ConfigService

    control = _control()
    project = _open(control, folder, read_only=True)
    try:
        emb = (
            embedder(ConfigService(control), control.local_principal) if mode != "speech" else None
        )
        with project.db.session() as s:
            found = lib.search(s, emb, query, mode, limit)
            items = lib.describe(s, found.hits)
    finally:
        project.close()
        control.db.dispose()
    if found.visual == "unavailable":
        click.echo("(visual search unavailable until an analysis fetches the text model)")
    if not items:
        click.echo("No results.")
    for it in items:
        tb = parse_rational(it["start"]["tb"])
        at = format_display(it["start"]["ticks"] * tb)
        status = it["status"] or "-"  # "-": not analysed yet
        click.echo(f"seg_{it['segment_id']:06d}  ast_{it['asset_id']:04d} @ {at}  [{status}]")
        for m in it["matched"]:
            click.echo(f"    {m}")


cli.add_command(config_group)
