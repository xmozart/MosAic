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


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def inspect(folder: Path) -> None:
    """Print the project's inventory: assets, unsupported files and sidecars."""
    from fractions import Fraction

    from sqlalchemy import select

    from mosaic.core.time import format_display
    from mosaic.storage.control import ControlDB
    from mosaic.storage.models_project import Asset, MediaFile, Sidecar
    from mosaic.storage.projects import open_project

    control = ControlDB()
    project = open_project(control, control.local_principal, folder)
    with project.db.session() as s:
        assets = list(s.scalars(select(Asset).order_by(Asset.id)))
        files = {m.id: m for m in s.scalars(select(MediaFile))}
        by_asset: dict[int, list[str]] = {}
        for m in files.values():
            if m.asset_id is not None:
                by_asset.setdefault(m.asset_id, []).append(m.rel_path)
        click.echo(f"{len(assets)} assets in {project.descriptor.name}")
        for a in assets:
            dur = ""
            if a.duration_ticks is not None and a.tb:
                tb = Fraction(a.tb)
                dur = format_display(a.duration_ticks * tb)
            flags = ",".join([*(a.flags or []), *(["vfr"] if a.vfr else [])])
            names = ", ".join(sorted(by_asset.get(a.id, [])))
            click.echo(
                f"  ast_{a.id:04d} {a.kind:11s} {a.status:11s} {a.profile:7s} {dur:>9s} "
                f"{a.rate or '':>11s} {a.color_hint:4s} rot={a.rotation:<3d} {flags:18s} "
                f"{names}"
            )
            if a.reason:
                click.echo(f"      reason: {a.reason}")
            if a.suggested_fix:
                click.echo(f"      fix: {a.suggested_fix}")
        away = [m for m in files.values() if m.status in ("offline", "missing")]
        if away:
            offline = sum(m.size for m in away if m.status == "offline")
            click.echo(f"{len(away)} files not available ({offline / 1e9:.2f} GB offline):")
            for m in sorted(away, key=lambda m: m.rel_path):
                click.echo(f"  {m.status:8s} {m.rel_path}: {m.reason}")
        for sc in s.scalars(select(Sidecar)):
            owner = files.get(sc.owner_media_file_id or -1)
            click.echo(
                f"  sidecar {files[sc.media_file_id].rel_path} -> "
                f"{owner.rel_path if owner else '-'}: {sc.status} {sc.reason or ''}"
            )
    project.close()


@cli.command("gen-long")
@click.argument("out_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--hours", type=int, default=40, show_default=True)
def gen_long(out_dir: Path, hours: int) -> None:
    """Generate the long synthetic project (reused when it already matches)."""
    from mosaic.devtools.longproject import LongSpec, generate

    spec = generate(out_dir, locate(), LongSpec(hours=hours))
    click.echo(f"{spec.clips} clips, {spec.hours} h in {out_dir}")
