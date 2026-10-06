"""Waveform peaks for the Player and clip detail (COMPONENTS.md Waveform; S11; ADR 0037).

A small L1 stage after the proxy: the proxy's audio decoded at 8 kHz mono, reduced to one
peak per bucket. A bucket is a whole number of samples, so its length is exact (invariant
3): ``{"ticks": samples, "tb": "1/8000"}``. Peaks are 0–255 (square-root scaled, which reads
like loudness), stored base64 in a JSON artifact keyed by the proxy (idempotent, invariant
9). The HTTP route only reads it.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Iterable, Iterator
from fractions import Fraction
from typing import Any

import numpy as np

from mosaic.core.keys import artifact_key
from mosaic.core.modes import task_mode
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import SkipTask, task
from mosaic.media import inventory
from mosaic.media import proxy as _proxy  # noqa: F401 - registers "proxy" first
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.run import stream_stdout
from mosaic.media.proxy import load_proxy
from mosaic.media.tools import media_tools
from mosaic.storage import provenance
from mosaic.storage.models_project import Asset
from mosaic.storage.projects import Project

WAVEFORM_VERSION = "waveform/1"
RATE = 8000
BUCKET_SAMPLES = 400  # 50 ms
MAX_BUCKETS = 36_000  # longer clips get longer buckets
CHUNK_SAMPLES = RATE  # read one second at a time (invariant 13)


def waveform_key(project: Project, proxy_key: str) -> str:
    return artifact_key(
        "waveform",
        project_id=project.id,
        inputs={"proxy": proxy_key},
        config={"rate": RATE, "bucket": BUCKET_SAMPLES, "max": MAX_BUCKETS},
        version=WAVEFORM_VERSION,
    )


def bucket_samples(duration: Fraction) -> int:
    """Samples per bucket for a clip of ``duration`` seconds (exact)."""
    total = max(1, math.ceil(duration * RATE))
    return max(BUCKET_SAMPLES, -(-total // MAX_BUCKETS))


def peaks(samples: np.ndarray, per_bucket: int) -> bytes:
    """One 0–255 peak per bucket (the last bucket may be partial)."""
    if samples.size == 0:
        return b""
    n = math.ceil(samples.size / per_bucket)
    padded = np.zeros(n * per_bucket, dtype=np.float32)
    padded[: samples.size] = np.abs(samples)
    top = padded.reshape(n, per_bucket).max(axis=1)
    return (np.sqrt(np.clip(top, 0.0, 1.0)) * 255).round().astype(np.uint8).tobytes()


def peaks_stream(chunks: Iterable[np.ndarray], per_bucket: int) -> bytes:
    """``peaks`` of the concatenated chunks, without holding them all (invariant 13): whole
    buckets are reduced as they arrive, the remainder carried to the next chunk, and the
    last bucket may be partial."""
    out = bytearray()
    carry = np.zeros(0, dtype=np.float32)
    for chunk in chunks:
        carry = np.concatenate([carry, chunk.astype(np.float32, copy=False)])
        whole = (carry.size // per_bucket) * per_bucket
        if whole:
            out += peaks(carry[:whole], per_bucket)
            carry = carry[whole:]
    out += peaks(carry, per_bucket)
    return bytes(out)


def _key(ctx: TaskContext) -> str:
    px = load_proxy(ctx.project, ctx.params["asset_id"], task_mode(ctx))
    return waveform_key(ctx.project, px.key)


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("waveform", _key(ctx))


@task("media.waveform", is_done=_is_done)
def waveform_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        has_audio = asset is not None and asset.audio_stream_index is not None
    if not has_audio:
        raise SkipTask("no sound")
    px = load_proxy(ctx.project, asset_id, task_mode(ctx))
    key = waveform_key(ctx.project, px.key)
    per_bucket = bucket_samples(Fraction(px.frames) / px.rate)
    binaries, _ = media_tools()

    def chunks() -> Iterator[np.ndarray]:
        reads = stream_stdout(
            binaries, builders.audio_pcm(px.path, RATE, 1), CHUNK_SAMPLES * 4, partial_tail=True
        )
        for i, buf in enumerate(reads):
            if i % 60 == 0:
                ctx.check_cancelled()
            usable = len(buf) - len(buf) % 4  # whole float32 samples
            yield np.frombuffer(buf[:usable], dtype=np.float32)

    out = peaks_stream(chunks(), per_bucket)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="waveform", algorithm_version=WAVEFORM_VERSION, input_keys=[px.key]
            ),
        )
    data = {
        "bucket": {"ticks": per_bucket, "tb": f"1/{RATE}"},
        "count": len(out),
        "peaks": base64.b64encode(bytes(out)).decode(),
    }
    ctx.project.artifacts.put_json("waveform", key, data, provenance_id=prov)
    return {"buckets": len(out)}


inventory.ASSET_STAGES.append(
    inventory.StageDef("waveform", "media.waveform", ResourceClass.CPU, after=("proxy",))
)
