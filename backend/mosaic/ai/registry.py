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


def _anthropic(key: str | None) -> Adapter:
    from mosaic.ai.adapters.anthropic.adapter import AnthropicAdapter

    if key is None:
        raise NotConfiguredError("the anthropic adapter needs an API key")
    return AnthropicAdapter(key)


def _fake(_key: str | None) -> Adapter:
    from mosaic.ai.adapters.fake.adapter import FakeAdapter

    return FakeAdapter()


def _anthropic_limits(model: str) -> AdapterLimits:
    from mosaic.ai.adapters.anthropic.adapter import limits

    return limits(model)


def _fake_limits(model: str) -> AdapterLimits:
    from mosaic.ai.adapters.fake.adapter import limits

    return limits(model)


@dataclass(frozen=True)
class ProviderEntry:
    factory: Callable[[str | None], Adapter]
    needs_key: bool
    limits: Callable[[str], AdapterLimits]


PROVIDERS: dict[str, ProviderEntry] = {
    "anthropic": ProviderEntry(_anthropic, needs_key=True, limits=_anthropic_limits),
    "fake": ProviderEntry(_fake, needs_key=False, limits=_fake_limits),
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
    if entry.needs_key and config.get(principal, "ai.local_only"):
        raise LocalOnlyError(
            f"{provider} is a cloud provider and ai.local_only is on; turn it off with "
            "`mosaic config set ai.local_only false` or choose a local provider"
        )
    key = config.key_for(principal, provider) if entry.needs_key else None
    return entry, key


def adapter_for(config: ConfigService, principal: Principal, provider: str) -> Adapter:
    entry, key = _ready(config, principal, provider)
    return entry.factory(key)


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
