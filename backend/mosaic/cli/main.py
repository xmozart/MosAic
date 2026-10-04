"""``mosaic``: the user-facing CLI. Thin wrappers over the same services as the API."""

from __future__ import annotations

from pathlib import Path

import click

from mosaic.storage.control import ControlDB
from mosaic.storage.placement import PlacementRefusedError


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
