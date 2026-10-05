"""Fake/replay adapter (ADR 0002 H): deterministic, offline, free. Used by all tests and CI.

Answers come from, in order: a recording in ``$MOSAIC_AI_REPLAY_DIR`` keyed by the request
hash (so real responses can be replayed in regression tests), or the responder registered
for the prompt, which builds a valid answer from the request's structured ``context``.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mosaic.ai.adapters.base import estimate_text_tokens
from mosaic.ai.types import AdapterError, AdapterLimits, RawCompletion, StructuredRequest
from mosaic.core.keys import digest

PROVIDER = "fake"
ENV_REPLAY = "MOSAIC_AI_REPLAY_DIR"

Responder = Callable[[StructuredRequest], dict[str, Any]]
RESPONDERS: dict[str, Responder] = {}
CALLS: list[str] = []  # prompt names of every completed call, for tests
_lock = threading.Lock()


def responder(prompt_name: str) -> Callable[[Responder], Responder]:
    def register(fn: Responder) -> Responder:
        RESPONDERS[prompt_name] = fn
        return fn

    return register


def request_hash(request: StructuredRequest, model: str) -> str:
    return digest(
        {
            "model": model,
            "prompt": [request.prompt_name, request.prompt_version],
            "system": request.system,
            "user": request.user_text,
            "images": [digest(img.data.hex()) for img in request.images],
        }
    )


class FakeAdapter:
    provider = PROVIDER

    def limits(self, model: str) -> AdapterLimits:
        return AdapterLimits(
            max_image_px=1568,
            max_images=20,
            supports_video=False,
            structured_output=True,
            context_window=200_000,
            local=True,
        )

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float:
        return 0.0

    def estimate_tokens(self, request: StructuredRequest) -> tuple[int, int]:
        return estimate_text_tokens(request.system, request.user_text), request.max_tokens

    def complete(
        self,
        request: StructuredRequest,
        model: str,
        json_schema: dict[str, Any],
        feedback: str | None,
    ) -> RawCompletion:
        replay = os.environ.get(ENV_REPLAY)
        if replay:
            path = Path(replay) / f"{request_hash(request, model)}.json"
            if path.is_file():
                text = path.read_text()
                return self._done(request, text, model)
        fn = RESPONDERS.get(request.prompt_name)
        if fn is None:
            raise AdapterError(
                f"fake adapter has no responder for {request.prompt_name!r}", retryable=False
            )
        answer = fn(request)
        if request.context.get("_fake_invalid_first") and feedback is None:
            answer = {"invalid": True}  # exercise the validate-and-retry path
        if request.context.get("_fake_always_invalid"):
            answer = {"invalid": True}
        return self._done(request, json.dumps(answer), model)

    def _done(self, request: StructuredRequest, text: str, model: str) -> RawCompletion:
        with _lock:
            CALLS.append(request.prompt_name)
        tokens_in, _ = self.estimate_tokens(request)
        return RawCompletion(
            text=text,
            tokens_in=tokens_in,
            tokens_out=len(text) // 3,
            model=model,
            latency_ms=0,
            stop_reason="end_turn",
        )


@responder("healthcheck")
def _healthcheck(_request: StructuredRequest) -> dict[str, Any]:
    return {"ok": True}
