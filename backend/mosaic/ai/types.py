"""Provider-neutral AI request and response types (ARCHITECTURE.md §11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    media_type: str  # image/jpeg | image/png
    width: int
    height: int


@dataclass(frozen=True)
class StructuredRequest:
    """One structured call: a rendered prompt plus images, answered as ``schema`` JSON.

    ``context`` is the structured data the prompt was rendered from; the fake adapter
    builds its deterministic answers from it, real adapters ignore it."""

    capability: str
    prompt_name: str
    prompt_version: int
    system: str
    user_text: str
    schema: type[BaseModel]
    images: tuple[ImageInput, ...] = ()
    max_tokens: int = 4096
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawCompletion:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    latency_ms: int
    stop_reason: str | None = None


@dataclass(frozen=True)
class AdapterLimits:
    """What an adapter can accept (ARCHITECTURE.md §11): drives mosaic geometry."""

    max_image_px: int  # longest edge the provider uses without downscaling
    max_images: int
    supports_video: bool
    structured_output: bool
    context_window: int
    local: bool


class AdapterError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class UnknownPriceError(RuntimeError):
    pass


# ------------------------------------------------------------ local capabilities


@dataclass(frozen=True)
class Word:
    start: float  # seconds from the start of the audio passed in (third-party floats; the
    end: float  # caller converts them to ticks at its boundary, ADR 0002 G)
    text: str
    probability: float


@dataclass(frozen=True)
class TranscriptPiece:
    words: list[Word]
    language: str | None
    avg_logprob: float
    no_speech_prob: float


@dataclass(frozen=True)
class SpeechSpan:
    start_sample: int
    end_sample: int
