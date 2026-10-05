"""Claude Code CLI adapter (ADR 0014): structured calls through the installed ``claude``
app and the user's own sign-in, no API key.

``claude -p`` runs with no tools, no session persistence and safe mode (no CLAUDE.md,
hooks, plugins or MCP) in an empty folder. The request goes in on stdin as one stream-json
user message (images as base64 blocks); the answer is the ``structured_output`` of the
final ``result`` event, checked against ``--json-schema``. The system prompt is MosAic's
fixed prompt text (argv); everything from the user's footage or trip goes through stdin.

Usage is billed to the user's Claude subscription, not per token, so ``cost_usd`` is 0
and job budgets do not apply; tokens are still recorded.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from mosaic.ai.adapters import cli_common
from mosaic.ai.adapters.base import estimate_text_tokens
from mosaic.ai.types import AdapterError, AdapterLimits, RawCompletion, StructuredRequest

PROVIDER = "claude-cli"
BINARY = "claude"
LOGIN_HINT = "open a terminal, run `claude` and sign in (/login)"
DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
MAX_IMAGE_PX = 1568


def limits(model: str) -> AdapterLimits:
    return AdapterLimits(
        max_image_px=MAX_IMAGE_PX,
        max_images=20,
        supports_video=False,
        structured_output=True,
        context_window=200_000,
        local=False,
    )


def build_argv(binary: str, model: str, system: str, json_schema: dict[str, Any]) -> list[str]:
    return [
        binary,
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--safe-mode",
        "--tools",
        "",
        "--no-session-persistence",
        "--system-prompt",
        system,
        "--json-schema",
        json.dumps(json_schema, separators=(",", ":")),
    ]


def build_stdin(request: StructuredRequest, feedback: str | None) -> str:
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
                "text": "Your previous answer did not validate:\n"
                + feedback
                + "\nReturn a corrected answer that satisfies the schema.",
            }
        )
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return json.dumps(message) + "\n"


def parse_events(stdout: str, model: str) -> tuple[str, int, int, str]:
    """``(answer json, tokens in, tokens out, served model)`` from stream-json output."""
    result: dict[str, Any] | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
    if result is None:
        raise AdapterError("claude ended without a result", retryable=True)
    if result.get("is_error") or result.get("subtype") != "success":
        message = str(result.get("result") or result.get("subtype") or "unknown error")
        raise cli_common.classify(BINARY, message, LOGIN_HINT)
    answer = result.get("structured_output")
    if answer is None:
        raise AdapterError("claude returned no structured output", retryable=False)
    usage = result.get("usage") or {}
    tokens_in = (
        int(usage.get("input_tokens", 0))
        + int(usage.get("cache_read_input_tokens", 0))
        + int(usage.get("cache_creation_input_tokens", 0))
    )
    tokens_out = int(usage.get("output_tokens", 0))
    served = next(
        (
            info.get("canonicalModel", name)
            for name, info in (result.get("modelUsage") or {}).items()
            if isinstance(info, dict) and info.get("canonicalModel")
        ),
        model,
    )
    return json.dumps(answer), tokens_in, tokens_out, str(served)


class ClaudeCliAdapter:
    provider = PROVIDER

    def __init__(self, binary_path: str = "", timeout_s: float = cli_common.DEFAULT_TIMEOUT_S):
        self.binary_path = binary_path
        self.timeout_s = timeout_s

    def limits(self, model: str) -> AdapterLimits:
        return limits(model)

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float:
        return 0.0  # billed to the user's subscription

    def estimate_tokens(self, request: StructuredRequest) -> tuple[int, int]:
        images = sum(
            min(i.width, MAX_IMAGE_PX) * min(i.height, MAX_IMAGE_PX) // 750 + 50
            for i in request.images
        )
        return images + estimate_text_tokens(request.system, request.user_text), request.max_tokens

    def complete(
        self,
        request: StructuredRequest,
        model: str,
        json_schema: dict[str, Any],
        feedback: str | None,
    ) -> RawCompletion:
        binary = cli_common.find_binary(BINARY, self.binary_path)
        argv = build_argv(binary, model, request.system, json_schema)
        with cli_common.workdir() as cwd:
            done = cli_common.run(
                argv, build_stdin(request, feedback), cwd, self.timeout_s, DROP_ENV
            )
        if done.returncode != 0 and '"type":"result"' not in done.stdout.replace(" ", ""):
            raise cli_common.classify(
                BINARY, done.stderr.strip() or f"exit code {done.returncode}", LOGIN_HINT
            )
        text, tokens_in, tokens_out, served = parse_events(done.stdout, model)
        return RawCompletion(text, tokens_in, tokens_out, served, done.latency_ms, "end_turn")
