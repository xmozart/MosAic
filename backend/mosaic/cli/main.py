"""``mosaic``: the user-facing CLI. Thin wrappers over the same services as the API."""

from __future__ import annotations

import click


@click.group()
@click.version_option(package_name="mosaic")
def cli() -> None:
    """MosAic: turn a folder of trip footage into story-driven edits."""
