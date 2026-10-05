"""Audio analysis (M0 step 7): VAD, transcription with word ticks, loudness."""

from __future__ import annotations

import json
import re
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run
from mosaic.media.proxy import load_proxy
from mosaic.storage.models_project import (
    Asset,
    AudioEvent,
    MediaFile,
    TechMetric,
    TranscriptSegment,
    TranscriptWord,
)
from mosaic.storage.projects import Project

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def analyzed(analyzed_corpus: Project) -> Project:
    return analyzed_corpus


def _asset(project: Project, name: str) -> Asset:
    with project.db.session() as s:
        mf = s.scalar(select(MediaFile).where(MediaFile.rel_path == name))
        assert mf is not None
        a = s.get(Asset, mf.asset_id)
        assert a is not None
        return a


def _norm(text: str) -> list[str]:
    return re.sub(r"[^a-z' ]", " ", text.lower()).split()


def _wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(len(ref), 1)


def test_transcript_and_word_ticks(analyzed: Project) -> None:
    case = next(
        c
        for c in json.loads((analyzed.root / "manifest.json").read_text())["cases"]
        if c["name"] == "speech"
    )
    asset = _asset(analyzed, "speech.mp4")
    tb = Fraction(asset.tb)
    with analyzed.db.session() as s:
        segs = list(
            s.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.asset_id == asset.id)
                .order_by(TranscriptSegment.start_ticks)
            )
        )
        words = list(
            s.scalars(
                select(TranscriptWord)
                .where(TranscriptWord.asset_id == asset.id)
                .order_by(TranscriptWord.start_ticks)
            )
        )
        vad = list(s.scalars(select(AudioEvent).where(AudioEvent.asset_id == asset.id)))
    hyp = _norm(" ".join(sg.text for sg in segs))
    assert _wer(_norm(case["transcript"]), hyp) <= 0.2, hyp
    offset = Fraction(case["speech_offset_ms"], 1000)
    speech_end = offset + Fraction(12485, 1000)
    assert words
    for w in words:
        assert isinstance(w.start_ticks, int)
        assert w.start_ticks <= w.end_ticks
        assert offset - Fraction(1, 10) <= w.start_ticks * tb <= speech_end, w.word
    starts = [w.start_ticks for w in words]
    assert starts == sorted(starts)
    assert vad
    assert min(v.start_ticks for v in vad) * tb <= words[0].start_ticks * tb
    assert max(v.end_ticks for v in vad) * tb >= words[-1].end_ticks * tb - Fraction(1, 2)


def test_no_speech_no_audio(analyzed: Project) -> None:
    for name in ("A001_basic.mp4", "no_audio.mp4"):
        asset = _asset(analyzed, name)
        with analyzed.db.session() as s:
            assert not list(
                s.scalars(select(TranscriptWord).where(TranscriptWord.asset_id == asset.id))
            )
    silent = _asset(analyzed, "no_audio.mp4")
    with analyzed.db.session() as s:
        assert not list(
            s.scalars(
                select(TechMetric).where(
                    TechMetric.asset_id == silent.id, TechMetric.name == "loudness"
                )
            )
        )


def test_loudness_matches_ffmpeg_ebur128(analyzed: Project, ffmpeg_bin: FFmpegBinaries) -> None:
    for name in ("A001_basic.mp4", "speech.mp4", "multi_audio.mov", "start_offset.mp4"):
        asset = _asset(analyzed, name)
        px = load_proxy(analyzed, asset.id)
        out = run(ffmpeg_bin, builders.ebur128_measure(px.path)).stderr
        ref = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out)[-1])
        with analyzed.db.session() as s:
            mine = s.scalar(
                select(TechMetric.value).where(
                    TechMetric.asset_id == asset.id, TechMetric.name == "lufs_integrated"
                )
            )
            per_second = list(
                s.scalars(
                    select(TechMetric).where(
                        TechMetric.asset_id == asset.id, TechMetric.name == "loudness"
                    )
                )
            )
        assert mine is not None
        assert abs(mine - ref) <= 0.5, (name, mine, ref)
        assert per_second
        assert per_second[-1].end_ticks <= asset.duration_ticks


def test_reanalysis_skips_audio(analyzed_session: Any) -> None:
    """Invariant 9: identical inputs, config and model mean no recompute."""
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.projects import open_project
    from tests.support.runner import run_job

    analyzed, control = analyzed_session  # the installation that holds the project's lease
    project = open_project(control, control.local_principal, analyzed.root)
    store = JobStore(control.db)
    job = submit_analysis(LocalExecutor(store), control.local_principal, project)
    assert run_job(control, job, timeout=900) == "done"
    audio_tasks = {t.id for t in store.tasks(job) if t.kind == "audio.analyze"}
    assert audio_tasks
    started = {e.task_id for e in store.events(job) if e.event == "started"}
    assert not started & audio_tasks
    project.close()
