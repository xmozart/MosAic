"""The 40-hour synthetic project (EVALUATION.md §1; ADR 0004, ADR 0031).

Many low-resolution, low-frame-rate clips spread over several trip days: the shape of a
long trip (hundreds of files, tens of thousands of samples and segments) at a fraction
of the decoding cost. Generated lazily: a manifest records the parameters, and a folder
that already matches them is reused.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import numpy as np

from mosaic.devtools.corpus import _h264, _sine, _write_frames, render_frame
from mosaic.media.ffmpeg.builders import SynthSpec
from mosaic.media.ffmpeg.capabilities import (
    FFmpegBinaries,
    ensure_license_allowed,
    probe_capabilities,
)

MANIFEST = "long-project.json"
PARTIAL = "long-project.partial.json"  # the spec of a generation in progress
GENERATOR_VERSION = 1


@dataclass(frozen=True)
class LongSpec:
    hours: int = 40
    clip_seconds: int = 360
    width: int = 192
    height: int = 108
    fps: int = 1
    days: int = 5
    audio_every: int = 10  # every n-th clip has sound (VAD runs on those)
    first_day: str = "2025-06-02"
    version: int = GENERATOR_VERSION

    @property
    def clips(self) -> int:
        return self.hours * 3600 // self.clip_seconds


def clip_name(i: int) -> str:
    return f"LONG_{i:04d}.mp4"


def _start(spec: LongSpec, i: int) -> datetime:
    per_day = -(-spec.clips // spec.days)
    day, slot = divmod(i, per_day)
    base = datetime.fromisoformat(spec.first_day).replace(hour=7, tzinfo=UTC)
    return base + timedelta(days=day, seconds=slot * spec.clip_seconds)


def _frames(spec: LongSpec, scene: int, seed: int) -> Callable[[int], np.ndarray]:
    return lambda n: render_frame(spec.width, spec.height, n, scene, seed)


def is_current(out: Path, spec: LongSpec) -> bool:
    manifest = out / MANIFEST
    if not manifest.is_file():
        return False
    if json.loads(manifest.read_text()) != asdict(spec):
        return False
    return all((out / clip_name(i)).is_file() for i in range(spec.clips))


def generate(out: Path, binaries: FFmpegBinaries, spec: LongSpec | None = None) -> LongSpec:
    """Write the project into ``out`` (reused when it already matches ``spec``)."""
    spec = spec or LongSpec()
    if is_current(out, spec):
        return spec
    out.mkdir(parents=True, exist_ok=True)
    (out / MANIFEST).unlink(missing_ok=True)
    partial = out / PARTIAL
    wanted = json.dumps(asdict(spec), indent=2)
    if not partial.is_file() or partial.read_text() != wanted:
        # Clips made for another spec are not reused: start over (cache files only).
        for f in out.glob("LONG_*"):
            f.unlink()
        partial.write_text(wanted)
    caps = probe_capabilities(binaries.ffmpeg)
    ensure_license_allowed(caps)
    rate = Fraction(spec.fps)
    frames = spec.clip_seconds * spec.fps
    for i in range(spec.clips):
        path = out / clip_name(i)
        if path.is_file():
            continue  # resumed generation: finished clips are kept
        tmp = path.with_name(path.name + ".part")  # not a media name: a scan skips it
        scene = (20 + (i * 37) % 70) * spec.fps  # 20–89 s scenes
        stamp = _start(spec, i).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        synth = SynthSpec(
            out=tmp,
            width=spec.width,
            height=spec.height,
            rate=rate,
            frames=frames,
            encoding=_h264(caps),
            audio=(_sine(220 + i % 7 * 40),) if i % spec.audio_every == 0 else (),
            metadata=(("creation_time", stamp),),
            container="mp4",
        )
        _write_frames(binaries, synth, _frames(spec, scene, i))
        tmp.rename(path)
    (out / MANIFEST).write_text(wanted)
    partial.unlink()
    return spec
