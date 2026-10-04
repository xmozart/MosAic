"""``mosaic``: the user-facing CLI. Thin wrappers over the same services as the API."""

from __future__ import annotations

from pathlib import Path

import click

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
