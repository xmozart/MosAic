"""Provider registry: capability → configured (adapter, model) (ADR 0003, ARCHITECTURE §11).

Provider and model come from the provider profile (``mosaic config ai set``); adapters for
other providers are added here when the owner chooses one.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mosaic.ai.adapters.base import Adapter
from mosaic.ai.capabilities import Embedder, Transcriber
from mosaic.ai.types import AdapterLimits
from mosaic.core.principal import Principal
from mosaic.core.settings import ProviderChoice
from mosaic.jobs.context import TaskContext
from mosaic.storage.config import ConfigService, NotConfiguredError


class LocalOnlyError(NotConfiguredError):
    pass


Factory = Callable[[ConfigService, Principal, str | None], Adapter]


def _anthropic(_config: ConfigService, _principal: Principal, key: str | None) -> Adapter:
    from mosaic.ai.adapters.anthropic.adapter import AnthropicAdapter

    if key is None:
        raise NotConfiguredError("the anthropic adapter needs an API key")
    return AnthropicAdapter(key)


def _fake(_config: ConfigService, _principal: Principal, _key: str | None) -> Adapter:
    from mosaic.ai.adapters.fake.adapter import FakeAdapter

    return FakeAdapter()


def _claude_cli(config: ConfigService, principal: Principal, _key: str | None) -> Adapter:
    from mosaic.ai.adapters.claude_cli.adapter import ClaudeCliAdapter

    return ClaudeCliAdapter(
        str(config.get(principal, "ai.cli.claude_path")),
        float(config.get(principal, "ai.cli.timeout_s")),
    )


def _codex_cli(config: ConfigService, principal: Principal, _key: str | None) -> Adapter:
    from mosaic.ai.adapters.codex_cli.adapter import CodexCliAdapter

    return CodexCliAdapter(
        str(config.get(principal, "ai.cli.codex_path")),
        float(config.get(principal, "ai.cli.timeout_s")),
    )


def _anthropic_limits(model: str) -> AdapterLimits:
    from mosaic.ai.adapters.anthropic.adapter import limits

    return limits(model)


def _fake_limits(model: str) -> AdapterLimits:
    from mosaic.ai.adapters.fake.adapter import limits

    return limits(model)


def _claude_cli_limits(model: str) -> AdapterLimits:
    from mosaic.ai.adapters.claude_cli.adapter import limits

    return limits(model)


def _codex_cli_limits(model: str) -> AdapterLimits:
    from mosaic.ai.adapters.codex_cli.adapter import limits

    return limits(model)


def _app_check(binary: str, setting: str) -> Callable[[ConfigService, Principal], None]:
    def check(config: ConfigService, principal: Principal) -> None:
        from mosaic.ai.adapters.cli_common import find_binary
        from mosaic.ai.types import AdapterError

        try:
            find_binary(binary, str(config.get(principal, setting)))
        except AdapterError as exc:
            raise NotConfiguredError(f"not configured: {exc}") from None

    return check


def _no_check(_config: ConfigService, _principal: Principal) -> None:
    return None


@dataclass(frozen=True)
class ProviderEntry:
    factory: Factory
    needs_key: bool
    limits: Callable[[str], AdapterLimits]
    remote: bool  # sends footage or text off this machine (blocked by ai.local_only)
    check: Callable[[ConfigService, Principal], None] = _no_check  # installed app present


PROVIDERS: dict[str, ProviderEntry] = {
    "anthropic": ProviderEntry(_anthropic, True, _anthropic_limits, remote=True),
    "claude-cli": ProviderEntry(
        _claude_cli,
        False,
        _claude_cli_limits,
        remote=True,
        check=_app_check("claude", "ai.cli.claude_path"),
    ),
    "codex-cli": ProviderEntry(
        _codex_cli,
        False,
        _codex_cli_limits,
        remote=True,
        check=_app_check("codex", "ai.cli.codex_path"),
    ),
    "fake": ProviderEntry(_fake, False, _fake_limits, remote=False),
}


def limits_for(choice: ProviderChoice) -> AdapterLimits:
    """The configured model's limits, without a key or a network call."""
    entry = PROVIDERS.get(choice.provider)
    if entry is None:
        raise NotConfiguredError(f"no adapter for provider {choice.provider!r}")
    return entry.limits(choice.model)


@dataclass(frozen=True)
class Resolved:
    adapter: Adapter
    choice: ProviderChoice


def _ready(
    config: ConfigService, principal: Principal, provider: str
) -> tuple[ProviderEntry, str | None]:
    """The provider's entry and key, or ``NotConfiguredError`` naming the fix."""
    entry = PROVIDERS.get(provider)
    if entry is None:
        raise NotConfiguredError(f"no adapter for provider {provider!r}")
    if entry.remote and config.get(principal, "ai.local_only"):
        raise LocalOnlyError(
            f"{provider} sends data off this machine and ai.local_only is on; turn it off with "
            "`mosaic config set ai.local_only false` or choose a local provider"
        )
    entry.check(config, principal)
    key = config.key_for(principal, provider) if entry.needs_key else None
    return entry, key


def adapter_for(config: ConfigService, principal: Principal, provider: str) -> Adapter:
    entry, key = _ready(config, principal, provider)
    return entry.factory(config, principal, key)


def resolve(config: ConfigService, principal: Principal, capability: str) -> Resolved:
    choice = config.provider(principal, capability)
    return Resolved(adapter_for(config, principal, choice.provider), choice)


# ------------------------------------------------------------- local capabilities

ENV_OVERRIDES = {"transcriber": "MOSAIC_STT_MODEL", "embedder": "MOSAIC_EMBED_VARIANT"}
"""Tests and CI pin small local models with these; normally the provider profile decides."""

_local_instances: dict[tuple[str, str], Any] = {}
_local_lock = threading.Lock()


def _local(config: ConfigService, principal: Principal, capability: str) -> Any:
    choice = config.provider(principal, capability)
    model = os.environ.get(ENV_OVERRIDES[capability]) or choice.model
    key = (choice.provider, model)
    with _local_lock:
        if key not in _local_instances:
            factory = LOCAL_PROVIDERS.get((capability, choice.provider))
            if factory is None:
                raise NotConfiguredError(
                    f"no {capability} adapter for provider {choice.provider!r}"
                )
            _local_instances[key] = factory(model)
        return _local_instances[key]


def transcriber(config: ConfigService, principal: Principal) -> Transcriber:
    t: Transcriber = _local(config, principal, "transcriber")
    return t


def embedder(config: ConfigService, principal: Principal) -> Embedder:
    e: Embedder = _local(config, principal, "embedder")
    return e


def _whisper(model: str) -> Any:
    from mosaic.ai.adapters.faster_whisper.transcriber import FasterWhisperTranscriber

    return FasterWhisperTranscriber(model)


def _siglip(model: str) -> Any:
    from mosaic.ai.adapters.siglip_onnx.embedder import SiglipEmbedder

    return SiglipEmbedder(model)


LOCAL_PROVIDERS: dict[tuple[str, str], Callable[[str], Any]] = {
    ("transcriber", "faster-whisper"): _whisper,
    ("embedder", "siglip-onnx"): _siglip,
}


def _task_config(ctx: TaskContext) -> tuple[ConfigService, Principal]:
    if ctx.control is None:
        raise NotConfiguredError("local AI capabilities need the control DB (run in a worker)")
    job = ctx.store.job(ctx.task.job_id)
    owner = Principal(user_id=job.user_id) if job else ctx.control.local_principal
    return ConfigService(ctx.control), owner  # the job owner's profile, like AIClient


def task_choice(ctx: TaskContext, capability: str) -> ProviderChoice:
    """The job owner's provider and model for ``capability``."""
    config, owner = _task_config(ctx)
    return config.provider(owner, capability)


def task_check_ready(ctx: TaskContext, capability: str) -> None:
    """Raise ``NotConfiguredError`` (naming the fix) if a call for ``capability`` could not
    be made now: unknown provider, cloud provider with ``ai.local_only`` on, or no key."""
    config, owner = _task_config(ctx)
    _ready(config, owner, config.provider(owner, capability).provider)


def task_embedder(ctx: TaskContext) -> Embedder:
    return embedder(*_task_config(ctx))


def task_transcriber(ctx: TaskContext) -> Transcriber:
    return transcriber(*_task_config(ctx))
