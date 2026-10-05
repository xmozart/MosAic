"""``Transcriber`` adapter ``faster-whisper``: local Whisper via CTranslate2.

The only module that imports faster-whisper. Times come back as float seconds relative to
the audio passed in; ``mosaic.audio.analysis`` converts them to ticks at its boundary.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any

import numpy as np
import numpy.typing as npt

from mosaic.ai.adapters.faster_whisper import av_shim
from mosaic.ai.types import SpeechSpan, TranscriptPiece, Word
from mosaic.core.paths import models_dir

PROVIDER = "faster-whisper"
# Supported models with pinned Hugging Face revisions (Systran/faster-whisper-*), so a key
# always means the same weights (invariant 9).
MODEL_REVISIONS = {
    "small": "536b0662742c02347bc0e980a01041f333bce120",
    "medium": "08e178d48790749d25932bbc082711ddcfdfbc4f",
}
BEAM = 5


class FasterWhisperTranscriber:
    provider = PROVIDER

    def __init__(self, name: str) -> None:
        if name not in MODEL_REVISIONS:
            raise ValueError(f"unsupported Whisper model {name!r}; use {sorted(MODEL_REVISIONS)}")
        self.name = name
        self.revision = MODEL_REVISIONS[name]
        self.model = f"{PROVIDER}/{name}@{self.revision[:12]}"
        self._model: Any = None
        self._lock = threading.Lock()

    def version_info(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "beam": BEAM,
            "faster_whisper": version("faster-whisper"),
            "ctranslate2": version("ctranslate2"),
        }

    def _whisper(self) -> Any:
        with self._lock:
            if self._model is None:
                av_shim.install()
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.name,
                    device="cpu",
                    compute_type="int8",
                    revision=self.revision,
                    download_root=str(models_dir() / "whisper"),
                )
            return self._model

    def speech_spans(self, audio: npt.NDArray[np.float32]) -> list[SpeechSpan]:
        av_shim.install()
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        return [
            SpeechSpan(int(sp["start"]), int(sp["end"]))
            for sp in get_speech_timestamps(audio, VadOptions())
        ]

    def transcribe(self, audio: npt.NDArray[np.float32]) -> Iterator[TranscriptPiece]:
        segments, info = self._whisper().transcribe(
            audio,
            word_timestamps=True,
            vad_filter=True,
            beam_size=BEAM,
            condition_on_previous_text=False,
        )
        for seg in segments:
            yield TranscriptPiece(
                words=[
                    Word(float(w.start), float(w.end), w.word, float(w.probability))
                    for w in (seg.words or [])
                ],
                language=info.language,
                avg_logprob=float(seg.avg_logprob),
                no_speech_prob=float(seg.no_speech_prob),
            )
