"""Anthropic adapter (Claude). The only module that imports the ``anthropic`` SDK.

Structured output uses ``output_config.format`` with a JSON schema. Per-model request
options follow the current API: Claude Haiku 4.5 accepts ``temperature`` (0 for
determinism); Claude Sonnet/Opus 5.x reject non-default sampling parameters and run
adaptive thinking, so they get an explicit ``effort`` instead (ADR 0012).
"""

from __future__ import annotations

import base64
import time
from typing import Any

import anthropic

from mosaic.ai.adapters.base import estimate_text_tokens
from mosaic.ai.types import (
    AdapterError,
    AdapterLimits,
    RawCompletion,
    StructuredRequest,
    UnknownPriceError,
)

PROVIDER = "anthropic"

# USD per million tokens (input, output), Anthropic first-party API rates as listed in the
# Claude API reference (models table cached 2026-09-25). Only models MosAic configures;
# any other model is refused for budgeted calls (UnknownPriceError).
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

# Request options per model family.
SAMPLING_TEMPERATURE = {"claude-haiku-4-5": 0.0}
EFFORT = {
    "claude-sonnet-5-5": "medium",
    "claude-opus-5-5": "medium",
}

MAX_IMAGE_PX = 1568  # longer edges are downscaled by the API


def limits(model: str) -> AdapterLimits:
    """Static per-model limits; needs no key (mosaic geometry is planned from them)."""
    return AdapterLimits(
        max_image_px=MAX_IMAGE_PX,
        max_images=20,
        supports_video=False,
        structured_output=True,
        context_window=200_000 if model.startswith("claude-haiku") else 1_000_000,
        local=False,
    )


class AnthropicAdapter:
    provider = PROVIDER

    def __init__(self, api_key: str, *, timeout_s: float = 180.0, max_retries: int = 2) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key, max_retries=max_retries, timeout=timeout_s
        )

    def quick(self) -> AnthropicAdapter:
        """A copy for interactive checks: short timeout, no retries."""
        clone = AnthropicAdapter.__new__(AnthropicAdapter)
        clone._client = self._client.with_options(timeout=20.0, max_retries=0)
        return clone

    def limits(self, model: str) -> AdapterLimits:
        return limits(model)

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float:
        if model not in PRICES:
            raise UnknownPriceError(
                f"no price table for {model}; budgets cannot be enforced for it"
            )
        pin, pout = PRICES[model]
        return (tokens_in * pin + tokens_out * pout) / 1_000_000

    def estimate_tokens(self, request: StructuredRequest) -> tuple[int, int]:
        image_tokens = sum(
            min(img.width, MAX_IMAGE_PX) * min(img.height, MAX_IMAGE_PX) // 750 + 50
            for img in request.images
        )
        text = estimate_text_tokens(request.system, request.user_text) + 400  # + schema
        return image_tokens + text, request.max_tokens

    def complete(
        self,
        request: StructuredRequest,
        model: str,
        json_schema: dict[str, Any],
        feedback: str | None,
    ) -> RawCompletion:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.media_type,
                    "data": base64.standard_b64encode(img.data).decode(),
                },
            }
            for img in request.images
        ]
        content.append({"type": "text", "text": request.user_text})
        if feedback:
            content.append(
                {
                    "type": "text",
                    "text": (
                        "Your previous answer did not validate:\n"
                        + feedback
                        + "\nReturn a corrected answer that satisfies the schema."
                    ),
                }
            )
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": json_schema}}
        params: dict[str, Any] = {}
        if model in SAMPLING_TEMPERATURE:
            # The 1.x SDK no longer types sampling parameters (current models reject them);
            # Haiku 4.5 still accepts temperature at the API, so it goes in the body.
            params["extra_body"] = {"temperature": SAMPLING_TEMPERATURE[model]}
        if model in EFFORT:
            output_config["effort"] = EFFORT[model]
        started = time.monotonic()
        try:
            # Request built dynamically per model; the response is checked at runtime below.
            messages_api: Any = self._client.messages
            response = messages_api.create(
                model=model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": content}],
                output_config=output_config,
                **params,
            )
        except (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        ) as exc:
            raise AdapterError(
                f"Anthropic temporarily unavailable: {type(exc).__name__}", retryable=True
            ) from None
        except anthropic.AuthenticationError:
            raise AdapterError(
                "the Anthropic key was rejected; run `mosaic config ai "
                "set-key --provider anthropic`",
                retryable=False,
            ) from None
        except anthropic.PermissionDeniedError:
            raise AdapterError(
                "the Anthropic key lacks permission for this model", retryable=False
            ) from None
        except anthropic.NotFoundError:
            raise AdapterError(f"unknown Anthropic model {model!r}", retryable=False) from None
        except anthropic.BadRequestError as exc:
            raise AdapterError(
                f"Anthropic rejected the request: {exc.message}", retryable=False
            ) from None
        except anthropic.APIStatusError as exc:
            raise AdapterError(
                f"Anthropic error {exc.status_code}", retryable=exc.status_code >= 500
            ) from None
        latency = int((time.monotonic() - started) * 1000)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise AdapterError(
                f"the model declined this request (category: {category})", retryable=False
            )
        if response.stop_reason == "max_tokens":
            raise AdapterError("the answer was cut off at max_tokens", retryable=False)
        text = next((b.text for b in response.content if b.type == "text"), "")
        return RawCompletion(
            text=text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=response.model,
            latency_ms=latency,
            stop_reason=response.stop_reason,
        )
