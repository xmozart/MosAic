"""``mosaic``: the user-facing CLI. Thin wrappers over the same services as the API."""

from __future__ import annotations

from pathlib import Path

import click

from mosaic.cli.config_cmd import config as config_group
from mosaic.storage.control import ControlDB
from mosaic.storage.placement import PlacementRefusedError
from mosaic.storage.projects import Project


@click.group()
@click.version_option(package_name="mosaic")
def cli() -> None:
    """MosAic: turn a folder of trip footage into story-driven edits."""


def _control() -> ControlDB:
    return ControlDB()


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--name", default=None, help="Project name (default: folder name).")
def init(folder: Path, name: str | None) -> None:
    """Create a project for FOLDER. Original footage is never modified."""
    from mosaic.storage.projects import init_project

    control = _control()
    try:
        project = init_project(control, control.local_principal, folder, name)
        click.echo(f"Project {project.descriptor.name} ({project.id})")
        click.echo(
            f"Placement: {project.descriptor.placement.value} — workspace {project.workspace}"
        )
        click.echo("Original footage stays where it is and will not be modified.")
        project.close()
    except PlacementRefusedError as exc:
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


def _open(control: ControlDB, folder: Path) -> Project:
    from mosaic.storage.projects import NotAProjectError, open_project

    try:
        return open_project(control, control.local_principal, folder)
    except (NotAProjectError, PlacementRefusedError) as exc:
        raise click.ClickException(str(exc)) from exc


def _follow(control: ControlDB, job_id: int) -> str:
    from mosaic.jobs.client import ensure_worker, wait_for_job
    from mosaic.jobs.model import JobProgress
    from mosaic.jobs.store import JobStore

    def show(p: JobProgress) -> None:
        item = f" — {p.current_item}" if p.current_item else ""
        click.echo(f"  [{p.pct:3d}%] {p.stage or p.status} {p.done}/{p.total}{item}")

    proc = ensure_worker(control)
    prog = wait_for_job(JobStore(control.db), job_id, show, control=control, worker=proc)
    return prog.status


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--mode",
    default="balanced",
    show_default=True,
    help="Analysis mode (M0 accepts balanced only).",
)
def analyze(folder: Path, mode: str) -> None:
    """Analyze FOLDER's footage into the project library."""
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import UnsupportedModeError, submit_analysis

    control = _control()
    project = _open(control, folder)
    try:
        job_id = submit_analysis(
            LocalExecutor(JobStore(control.db)), control.local_principal, project, mode
        )
        click.echo(f"Analysis job {job_id} ({mode})")
        status = _follow(control, job_id)
    except UnsupportedModeError as exc:
        raise click.ClickException(str(exc)) from exc
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
    project = _open(control, folder)
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


cli.add_command(config_group)
