"""Import faster-whisper without PyAV (ADR 0009).

PyAV wheels bundle a GPL FFmpeg (x264/x265), so PyAV is excluded from the environment.
faster-whisper imports ``av`` at module load but uses it only in ``decode_audio``, which
is never called: MosAic decodes audio with its own LGPL FFmpeg and passes numpy arrays.
"""

from __future__ import annotations

import sys
import types
from typing import Any


class _Unavailable(types.ModuleType):
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            # Introspection (pickle, Hypothesis, importlib) must see an ordinary module.
            raise AttributeError(name)
        raise RuntimeError(
            "PyAV is not available in MosAic (ADR 0009); decode audio with MosAic's FFmpeg "
            "(mosaic.media.ffmpeg.builders.audio_pcm), not faster_whisper.decode_audio"
        )


def install() -> None:
    """Register a placeholder ``av`` module if the real one is not installed."""
    if "av" in sys.modules:
        return
    try:
        import av  # noqa: F401
    except ImportError:
        sys.modules["av"] = _Unavailable("av")
