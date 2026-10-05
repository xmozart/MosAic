"""Audio analysis per asset (ARCHITECTURE.md §8 stage 7): loudness, VAD, transcription.

Audio comes from the asset's proxy, whose audio track is already aligned to logical time 0
and concatenated across chapters (ADR 0009). Whisper and VAD report float seconds; they
become ticks here, at the module boundary (ADR 0002 G).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import delete

from mosaic.ai.registry import task_transcriber
from mosaic.audio.loudness import RATE as LOUD_RATE
from mosaic.audio.loudness import AudioStats, LoudnessMeter
from mosaic.core.keys import artifact_key
from mosaic.core.time import Rounding, SourceTime, parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, task
from mosaic.media import inventory
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.run import stream_stdout
from mosaic.media.proxy import load_proxy
from mosaic.media.tools import media_tools
from mosaic.storage import provenance
from mosaic.storage.models_project import (
    Asset,
    AudioEvent,
    TechMetric,
    TranscriptSegment,
    TranscriptWord,
)

AUDIO_VERSION = "audio/1"
STT_RATE = 16_000
BLOCK = Fraction(600)  # transcribe in 10-minute blocks (bounded memory)
OVERLAP = Fraction(2)


def _config(ctx: TaskContext) -> dict[str, Any]:
    return {
        **task_transcriber(ctx).version_info(),
        "block": BLOCK,
        "overlap": OVERLAP,
        "vad": "silero",
    }


def _key(ctx: TaskContext) -> str:
    px = load_proxy(ctx.project, ctx.params["asset_id"])
    return artifact_key(
        "audio",
        project_id=ctx.project.id,
        inputs={"proxy": px.key, "asset": ctx.params["asset_id"]},
        config=_config(ctx),
        version=AUDIO_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("audio", _key(ctx))


def to_ticks(seconds: Fraction, tb: Fraction) -> int:
    return SourceTime.from_seconds(seconds, tb, Rounding.NEAREST).ticks


def float_to_ticks(base: Fraction, seconds: float, tb: Fraction) -> int:
    """Boundary conversion for float times from Whisper/VAD, relative to ``base``."""
    return SourceTime.from_float_offset(base, seconds, tb).ticks


def _loudness(ctx: TaskContext, proxy_path: Path) -> AudioStats:
    binaries, _ = media_tools()
    meter = LoudnessMeter()
    chunk = LOUD_RATE * 2 * 4  # one second of stereo float32
    for i, buf in enumerate(
        stream_stdout(binaries, builders.audio_pcm(proxy_path, LOUD_RATE, 2), chunk)
    ):
        if i % 60 == 0:
            ctx.check_cancelled()
        meter.feed(np.frombuffer(buf, dtype=np.float32).reshape(-1, 2).astype(np.float64))
    return meter.result()


def _block_audio(
    ctx: TaskContext, proxy_path: Path, start: Fraction, length: Fraction
) -> npt.NDArray[np.float32]:
    binaries, _ = media_tools()
    bufs = list(
        stream_stdout(
            binaries,
            builders.audio_pcm(proxy_path, STT_RATE, 1, start=start, duration=length),
            STT_RATE * 4,
        )
    )
    return np.frombuffer(b"".join(bufs), dtype=np.float32) if bufs else np.zeros(0, np.float32)


@task("audio.analyze", is_done=_is_done)
def audio_task(ctx: TaskContext) -> dict[str, Any]:
    asset_id = ctx.params["asset_id"]
    tr = task_transcriber(ctx)
    key = _key(ctx)
    px = load_proxy(ctx.project, asset_id)
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        if asset is None or asset.tb is None:
            raise PermanentError(f"asset {asset_id} has no timeline")
        tb = parse_rational(asset.tb)
        duration = asset.duration_ticks or 0
        has_audio = asset.audio_stream_index is not None
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="audio",
                algorithm_version=AUDIO_VERSION,
                model=tr.model,
                model_version=tr.model,
                provider=tr.provider,
                input_keys=[px.key],
            ),
        )
        for model in (TranscriptWord, TranscriptSegment, AudioEvent):
            s.execute(delete(model).where(model.asset_id == asset_id))
        s.execute(
            delete(TechMetric).where(
                TechMetric.asset_id == asset_id,
                TechMetric.name.in_(
                    [
                        "loudness",
                        "wind",
                        "lufs_integrated",
                        "loudness_range",
                        "peak_dbfs",
                        "clip_fraction",
                    ]
                ),
            )
        )
    if not has_audio:
        ctx.project.artifacts.put_json("audio", key, {"silent": True}, provenance_id=prov)
        return {"silent": True}

    ctx.set_stage("loudness")
    stats = _loudness(ctx, px.path)
    with ctx.write() as s:
        for name, value in (
            ("lufs_integrated", stats.integrated_lufs),
            ("loudness_range", stats.loudness_range),
            ("peak_dbfs", stats.peak_dbfs),
            ("clip_fraction", stats.clip_fraction),
        ):
            s.add(
                TechMetric(
                    asset_id=asset_id,
                    start_ticks=0,
                    end_ticks=duration,
                    name=name,
                    value=value,
                    provenance_id=prov,
                )
            )
        for sec, (lu, wind) in enumerate(zip(stats.per_second_lufs, stats.wind, strict=True)):
            a = to_ticks(Fraction(sec), tb)
            b = min(to_ticks(Fraction(sec + 1), tb), duration)
            if a >= duration:
                break
            s.add(
                TechMetric(
                    asset_id=asset_id,
                    start_ticks=a,
                    end_ticks=b,
                    name="loudness",
                    value=lu,
                    provenance_id=prov,
                )
            )
            s.add(
                TechMetric(
                    asset_id=asset_id,
                    start_ticks=a,
                    end_ticks=b,
                    name="wind",
                    value=wind,
                    provenance_id=prov,
                )
            )

    ctx.set_stage("transcription")
    total = duration * tb
    words = speech = 0
    start = Fraction(0)
    while start < total:
        ctx.check_cancelled()
        lead = OVERLAP if start > 0 else Fraction(0)
        read_from = start - lead
        audio = _block_audio(ctx, px.path, read_from, BLOCK + lead + OVERLAP)
        end = min(start + BLOCK, total)

        def owned(t: Fraction, _start: Fraction = start, _end: Fraction = end) -> bool:
            return _start <= t < _end

        spans = tr.speech_spans(audio)
        with ctx.write() as s:
            for sp in spans:
                # Each block records the part of a span inside its own [start, end): a span
                # crossing a block edge becomes two adjacent events, nothing is lost.
                sp_start: Fraction = max(read_from + Fraction(sp.start_sample, STT_RATE), start)
                sp_end: Fraction = min(read_from + Fraction(sp.end_sample, STT_RATE), end)
                if sp_end > sp_start:
                    s.add(
                        AudioEvent(
                            asset_id=asset_id,
                            kind="speech",
                            start_ticks=to_ticks(sp_start, tb),
                            end_ticks=to_ticks(sp_end, tb),
                            provenance_id=prov,
                        )
                    )
                    speech += 1
        if spans:
            segments = tr.transcribe(audio)
            for seg in segments:
                seg_words = [
                    w
                    for w in seg.words
                    if owned(SourceTime.from_float_offset(read_from, w.start, tb).seconds)
                ]
                if not seg_words:
                    continue
                with ctx.write() as s:
                    row = TranscriptSegment(
                        asset_id=asset_id,
                        start_ticks=float_to_ticks(read_from, seg_words[0].start, tb),
                        end_ticks=min(float_to_ticks(read_from, seg_words[-1].end, tb), duration),
                        text="".join(w.text for w in seg_words).strip(),
                        language=seg.language,
                        avg_logprob=float(seg.avg_logprob),
                        no_speech_prob=float(seg.no_speech_prob),
                        provenance_id=prov,
                    )
                    s.add(row)
                    s.flush()
                    for w in seg_words:
                        s.add(
                            TranscriptWord(
                                asset_id=asset_id,
                                segment_id=row.id,
                                start_ticks=float_to_ticks(read_from, w.start, tb),
                                end_ticks=min(float_to_ticks(read_from, w.end, tb), duration),
                                word=w.text.strip(),
                                probability=float(w.probability),
                            )
                        )
                        words += 1
        start = end
    summary = {
        "lufs": stats.integrated_lufs,
        "speech_spans": speech,
        "words": words,
        "model": tr.model,
    }
    ctx.project.artifacts.put_json("audio", key, summary, provenance_id=prov)
    return summary


inventory.ASSET_STAGES.append(
    inventory.StageDef("audio", "audio.analyze", ResourceClass.CPU, after=("proxy",))
)
