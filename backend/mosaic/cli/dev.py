"""``mosaic-dev``: developer tools (synthetic corpus, inspection)."""

from __future__ import annotations

from pathlib import Path

import click

from mosaic.media.ffmpeg.capabilities import locate


@click.group()
def cli() -> None:
    """MosAic developer tools."""


@cli.command("gen-corpus")
@click.argument("out_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--only", multiple=True, help="Generate only these case groups.")
@click.option("--ffmpeg-dir", type=click.Path(path_type=Path), default=None)
def gen_corpus(out_dir: Path, only: tuple[str, ...], ffmpeg_dir: Path | None) -> None:
    """Generate the synthetic corpus (EVALUATION.md §1) into OUT_DIR."""
    from mosaic.devtools.corpus import CorpusGenerator

    gen = CorpusGenerator(out_dir, locate(ffmpeg_dir))
    for case in gen.generate(set(only) if only else None):
        status = f"skipped: {case.skipped_reason}" if case.skipped_reason else ", ".join(case.files)
        click.echo(f"{case.name:18s} {status}")
