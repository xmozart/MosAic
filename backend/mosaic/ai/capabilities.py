"""Capability interfaces (ARCHITECTURE.md §11). Business code depends on these and on
``ai.registry`` resolvers, never on a concrete adapter module.

Cloud capabilities (VisionAnalyzer, StoryPlanner, ShotSelector, Critic) are structured
calls through ``ai.client.AIClient``; local ones are the protocols below.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from PIL import Image

from mosaic.ai.types import SpeechSpan, TranscriptPiece


class Transcriber(Protocol):
    provider: str
    model: str  # exact identity (name and pinned revision), part of artifact keys

    def version_info(self) -> dict[str, Any]: ...

    def speech_spans(self, audio: npt.NDArray[np.float32]) -> list[SpeechSpan]:
        """Voice activity over 16 kHz mono audio."""
        ...

    def transcribe(self, audio: npt.NDArray[np.float32]) -> Iterator[TranscriptPiece]: ...


class Embedder(Protocol):
    provider: str
    model: str  # exact identity (model, variant, revision); names the vector index
    dim: int

    def embed(self, images: Sequence[Image.Image]) -> npt.NDArray[np.float32]:
        """L2-normalized embeddings, shape (n, dim). Weights load on first use."""
        ...
