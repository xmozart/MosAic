"""Telemetry stage: GoPro GPMF gyro → per-second shake (ARCHITECTURE.md §8 stage 6).

Gyro shake (``shake_gyro``, rad/s) is the primary shake metric when present; optical-flow
``shake`` from the visual stage is the fallback (``library.quality.shake_metric_name``).
Assets without a readable GPMF track end ``skipped``, so segments never wait on telemetry.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from sqlalchemy import delete, select

from mosaic.core.keys import artifact_key
from mosaic.core.time import Rounding, SourceTime, parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, SkipTask, task
from mosaic.media import gpmf, inventory
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.run import FFmpegError, run
from mosaic.media.tools import media_tools
from mosaic.storage import provenance
from mosaic.storage.models_project import Asset, AssetFile, MediaFile, MediaStream, TechMetric

TELEMETRY_VERSION = "telemetry/1"


def second_ranges(
    start: int, duration: int, tb: Fraction, values: list[float]
) -> list[tuple[int, int, float]]:
    """Per-second values of one chapter → ``(start_ticks, end_ticks, value)`` in logical
    ticks; the last range ends at the chapter end."""
    out = []
    for sec, value in enumerate(values):
        a = start + SourceTime.from_seconds(Fraction(sec), tb, Rounding.NEAREST).ticks
        b = min(start + SourceTime.from_seconds(Fraction(sec + 1), tb).ticks, start + duration)
        if a < b:
            out.append((a, b, value))
    return out


def _gpmd_streams(ctx: TaskContext, asset_id: int) -> list[tuple[str, str, int, int, int]]:
    """``(rel_path, fingerprint, stream_index, logical_start, duration)`` per chapter."""
    with ctx.project.db.session() as s:
        rows = s.execute(
            select(
                MediaFile.rel_path,
                MediaFile.fingerprint,
                MediaStream.stream_index,
                AssetFile.logical_start_ticks,
                AssetFile.duration_ticks,
            )
            .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
            .join(MediaStream, MediaStream.media_file_id == MediaFile.id)
            .where(AssetFile.asset_id == asset_id, MediaStream.codec_tag == "gpmd")
            .order_by(AssetFile.order)
        )
        return [tuple(r) for r in rows]  # type: ignore[misc]


def _key(ctx: TaskContext, chapters: list[Any]) -> str:
    return artifact_key(
        "telemetry",
        project_id=ctx.project.id,
        inputs={"asset": ctx.params["asset_id"], "streams": [(c[1], c[2]) for c in chapters]},
        version=TELEMETRY_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    chapters = _gpmd_streams(ctx, ctx.params["asset_id"])
    return bool(chapters) and ctx.project.artifacts.exists("telemetry", _key(ctx, chapters))


@task("media.telemetry", is_done=_is_done)
def telemetry_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    chapters = _gpmd_streams(ctx, asset_id)
    if not chapters:
        raise SkipTask("no GPMF telemetry track")
    binaries, _ = media_tools()
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        if asset is None or asset.tb is None:
            raise PermanentError(f"asset {asset_id} has no timeline")
        tb = parse_rational(asset.tb)
    rows: list[tuple[int, int, float]] = []
    total_samples = 0
    for rel, _fp, idx, start, dur in chapters:
        try:
            data = run(
                binaries, builders.extract_data_stream(ctx.project.root / rel, idx), timeout=600
            ).stdout
        except FFmpegError as exc:
            raise SkipTask(f"telemetry unreadable in {rel}: {exc}") from exc
        samples = gpmf.gyro_samples(data)
        total_samples += len(samples)
        values = gpmf.shake_per_second(samples, dur * tb)
        rows += second_ranges(start, dur, tb, values)
    if not total_samples:
        raise SkipTask("GPMF track has no gyro samples")
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="telemetry",
                algorithm_version=TELEMETRY_VERSION,
                input_keys=[c[1] for c in chapters],
            ),
        )
        s.execute(
            delete(TechMetric).where(
                TechMetric.asset_id == asset_id, TechMetric.name == "shake_gyro"
            )
        )
        for a, b, value in rows:
            s.add(
                TechMetric(
                    asset_id=asset_id,
                    start_ticks=a,
                    end_ticks=b,
                    name="shake_gyro",
                    value=value,
                    provenance_id=prov,
                )
            )
    ctx.project.artifacts.put_json(
        "telemetry",
        _key(ctx, chapters),
        {"gyro_samples": total_samples, "seconds": len(rows)},
        provenance_id=prov,
    )
    return {"gyro_samples": total_samples}


inventory.ASSET_STAGES.append(inventory.StageDef("telemetry", "media.telemetry", ResourceClass.IO))
