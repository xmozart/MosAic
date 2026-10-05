"""Codex CLI adapter (ADR 0014): structured calls through the installed ``codex`` app and
the user's own sign-in, no API key.

``codex exec`` runs read-only, ephemeral, with its tools switched off and without the
user's config file or exec rules, in an empty folder. The prompt (system text first, then
the user text) goes in on stdin, images as temporary files (``-i``), the schema as
``--output-schema``; the answer is the last agent message (``-o``). Usage is billed to the
user's ChatGPT plan, so ``cost_usd`` is 0 and job budgets do not apply; tokens come from
the ``turn.completed`` event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mosaic.ai.adapters import cli_common
from mosaic.ai.adapters.base import estimate_text_tokens
from mosaic.ai.types import AdapterError, AdapterLimits, RawCompletion, StructuredRequest

PROVIDER = "codex-cli"
BINARY = "codex"
LOGIN_HINT = "open a terminal and run `codex login`"
DROP_ENV = ("OPENAI_API_KEY", "CODEX_API_KEY")
MAX_IMAGE_PX = 1568  # same sheets as other providers, so cached mosaics are shared
_EXT = {"image/jpeg": ".jpg", "image/png": ".png"}
# Codex features that give the model tools (shell, browser, apps...). MosAic only needs an
# answer, so every tool is switched off; the read-only sandbox is a second line.
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "image_generation",
    "apps",
    "plugins",
    "multi_agent",
    "hooks",
    "goals",
    "tool_suggest",
    "skill_mcp_dependency_install",
)


def limits(model: str) -> AdapterLimits:
    return AdapterLimits(
        max_image_px=MAX_IMAGE_PX,
        max_images=10,
        supports_video=False,
        structured_output=True,
        context_window=200_000,
        local=False,
    )


def build_argv(
    binary: str, model: str, schema_file: Path, last_file: Path, images: list[Path]
) -> list[str]:
    argv = [
        binary,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        *(arg for feature in DISABLED_FEATURES for arg in ("--disable", feature)),
        "-m",
        model,
        "--output-schema",
        str(schema_file),
        "-o",
        str(last_file),
    ]
    for img in images:
        argv += ["-i", str(img)]
    argv.append("-")  # prompt from stdin
    return argv


def build_stdin(request: StructuredRequest, feedback: str | None) -> str:
    parts = [
        "# Instructions",
        request.system,
        "# Task",
        request.user_text,
        "Do not run commands or read files; answer only from this message and the "
        "attached images, as JSON matching the output schema.",
    ]
    if feedback:
        parts += [
            "# Your previous answer did not validate",
            feedback,
            "Return a corrected answer that satisfies the schema.",
        ]
    return "\n\n".join(parts) + "\n"


def parse_events(stdout: str) -> tuple[int, int]:
    """Token usage; raises on a failed turn."""
    tokens_in = tokens_out = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "turn.failed":
            message = str((event.get("error") or {}).get("message", "turn failed"))
            raise cli_common.classify(BINARY, message, LOGIN_HINT)
        if kind == "turn.completed":
            usage = event.get("usage") or {}
            tokens_in += int(usage.get("input_tokens", 0))
            tokens_out += int(usage.get("output_tokens", 0))
    return tokens_in, tokens_out


class CodexCliAdapter:
    provider = PROVIDER

    def __init__(self, binary_path: str = "", timeout_s: float = cli_common.DEFAULT_TIMEOUT_S):
        self.binary_path = binary_path
        self.timeout_s = timeout_s

    def limits(self, model: str) -> AdapterLimits:
        return limits(model)

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float:
        return 0.0  # billed to the user's plan

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
        with cli_common.workdir() as cwd:
            schema_file = cwd / "schema.json"
            schema_file.write_text(json.dumps(json_schema))
            last_file = cwd / "answer.json"
            images = []
            for n, img in enumerate(request.images):
                path = cwd / f"image-{n:02d}{_EXT.get(img.media_type, '.jpg')}"
                path.write_bytes(img.data)
                images.append(path)
            done = cli_common.run(
                build_argv(binary, model, schema_file, last_file, images),
                build_stdin(request, feedback),
                cwd,
                self.timeout_s,
                DROP_ENV,
            )
            tokens_in, tokens_out = parse_events(done.stdout)
            if done.returncode != 0:
                raise cli_common.classify(
                    BINARY, done.stderr.strip()[-400:] or f"exit code {done.returncode}", LOGIN_HINT
                )
            if not last_file.is_file():
                raise AdapterError("codex returned no answer", retryable=True)
            text = last_file.read_text().strip()
        return RawCompletion(text, tokens_in, tokens_out, model, done.latency_ms, "end_turn")
