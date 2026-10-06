"""Hardware benchmark (M1 step 12, ADR 0030; ANALYSIS_MODES.md §4).

Measures, on this computer, the local work that dominates analysis time, per minute of
4K footage: decoding into each proxy size, and the per-frame visual pass. It also times
image embeddings when the embedder is available. Estimates use the result in place of
the M0 speed factors.

The test clip is generated (never the owner's footage) in the app's temporary folder and
removed afterwards. Results are integer milliseconds; they are measurements for display
estimates, never authoritative times (invariant 3).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.core.paths import app_data_dir
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import PermanentError, task
from mosaic.media import hardware
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.run import FFmpegError, run
from mosaic.media.proxy import PROXY_BITRATE, QUICK_BITRATE
from mosaic.media.tools import media_tools, working_h264_encoders
from mosaic.media.visual import frame_pass
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import HardwareBenchmark

log = logging.getLogger(__name__)

BENCH_VERSION = "benchmark/1"
SOURCE = (3840, 2160, 30, 4)  # width, height, fps, seconds: typical modern camera footage
PROXIES = {"lrf_or_540": (960, 540, QUICK_BITRATE), "720": (1280, 720, PROXY_BITRATE)}
EMBED_IMAGES = 16


@dataclass(frozen=True)
class Benchmark:
    fingerprint: str
    version: str
    hardware: dict[str, Any]
    result: dict[str, Any]
    created_at: str

    def ms_per_minute(self, stage: str) -> int | None:
        value = self.result.get("ms_per_minute", {}).get(stage)
        return int(value) if value is not None else None

    @property
    def embed_ms(self) -> int | None:
        value = self.result.get("embed_ms_per_image")
        return int(value) if value is not None else None

    def as_json(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "version": self.version,
            "result": self.result,
            "created_at": self.created_at,
        }


def _per_minute(elapsed_s: float, footage_s: int) -> int:
    return round(elapsed_s * 60_000 / footage_s)


def measure(
    workdir: Path,
    embed: Callable[[Sequence[Image.Image]], Any] | None = None,
    check: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    """Run the benchmark in ``workdir`` and return its result (no DB access)."""
    binaries, _ = media_tools()
    encoders = working_h264_encoders()
    if not encoders:
        raise PermanentError("no working H.264 encoder: the benchmark cannot make its clip")
    encoder = encoders[0]
    w, h, fps, seconds = SOURCE
    src = workdir / "source.mp4"
    run(binaries, builders.bench_source(src, w, h, fps, seconds, encoder))
    check()
    hwaccel = "videotoolbox" if encoder == "h264_videotoolbox" else None
    per_minute: dict[str, int] = {}
    proxy_720: Path | None = None
    for name, (pw, ph, bitrate) in PROXIES.items():
        out = workdir / f"proxy-{name}.mp4"
        spec = builders.ProxySpec(
            inputs=[src],
            video_index=0,
            audio_index=None,
            width=pw,
            height=ph,
            rate=Fraction(fps),
            hdr=None,
            full_range=False,
            encoder=encoder,
            bitrate=bitrate,
            video_starts=[Fraction(0)],
            video_durations=[Fraction(seconds)],
            hwaccel=hwaccel,
            out=out,
        )
        started = time.perf_counter()
        try:
            run(binaries, builders.proxy(spec))
        except FFmpegError:
            if spec.hwaccel is None:
                raise
            spec.hwaccel = None  # as the proxy task does: decode in software
            started = time.perf_counter()
            run(binaries, builders.proxy(spec))
        per_minute[name] = _per_minute(time.perf_counter() - started, seconds)
        if name == "720":
            proxy_720 = out
        check()
    assert proxy_720 is not None
    started = time.perf_counter()
    frame_pass(proxy_720, 1280, 720, check)
    per_minute["analysis"] = _per_minute(time.perf_counter() - started, seconds)
    embed_ms: int | None = None
    if embed is not None:
        frames = [
            Image.new("RGB", (640, 360), (i * 15, 90, 200 - i * 10)) for i in range(EMBED_IMAGES)
        ]
        try:
            embed(frames[:1])  # load the model outside the timing
            started = time.perf_counter()
            embed(frames[:EMBED_IMAGES])
            embed_ms = round((time.perf_counter() - started) * 1000 / EMBED_IMAGES)
        except Exception as exc:  # offline, or no model yet: estimates use the default
            log.info("benchmark: image embeddings not timed: %s", exc)
            embed_ms = None
    return {
        "source": {"width": w, "height": h, "fps": fps, "seconds": seconds},
        "encoder": encoder,
        "ms_per_minute": per_minute,
        "embed_ms_per_image": embed_ms,
    }


def latest(control: ControlDB, hw: hardware.Hardware | None = None) -> Benchmark | None:
    """The stored benchmark of this computer (current version), if any."""
    fp = (hw or hardware.probe()).fingerprint
    with control.db.session() as s:
        row = s.scalar(
            select(HardwareBenchmark).where(
                HardwareBenchmark.fingerprint == fp, HardwareBenchmark.version == BENCH_VERSION
            )
        )
        if row is None:
            return None
        return Benchmark(row.fingerprint, row.version, row.hardware, row.result, row.created_at)


def save(control: ControlDB, hw: hardware.Hardware, result: dict[str, Any]) -> Benchmark:
    with control.db.session() as s:
        row = s.scalar(
            select(HardwareBenchmark).where(
                HardwareBenchmark.fingerprint == hw.fingerprint,
                HardwareBenchmark.version == BENCH_VERSION,
            )
        )
        if row is None:
            row = HardwareBenchmark(fingerprint=hw.fingerprint, version=BENCH_VERSION)
            s.add(row)
        row.hardware = hw.as_json()
        row.result = result
        row.created_at = now_iso()
    found = latest(control, hw)
    assert found is not None
    return found


def _is_done(ctx: TaskContext) -> bool:
    if ctx.params.get("force") or ctx.control is None:
        return False
    return latest(ctx.control) is not None


@task("system.benchmark", is_done=_is_done)
def benchmark_task(ctx: TaskContext) -> dict[str, Any]:
    if ctx.control is None:
        raise PermanentError("the benchmark needs the control DB (run inside a worker)")
    embed: Callable[[Sequence[Image.Image]], Any] | None = None
    try:
        from mosaic.ai.registry import task_embedder

        embed = task_embedder(ctx).embed
    except Exception as exc:
        log.info("benchmark: no embedder: %s", exc)
        embed = None
    tmp_root = app_data_dir() / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="benchmark-", dir=tmp_root))
    try:
        result = measure(workdir, embed, ctx.check_cancelled)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    bench = save(ctx.control, hardware.probe(), result)
    return {"benchmark": bench.result}
