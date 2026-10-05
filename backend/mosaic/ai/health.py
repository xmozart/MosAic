"""``mosaic config ai test`` and ``POST /secrets/{ref}/validate``: one minimal call."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from mosaic.ai.adapters.base import strict_schema
from mosaic.ai.prompts.loader import load
from mosaic.ai.registry import adapter_for
from mosaic.ai.types import AdapterError, StructuredRequest
from mosaic.core.clock import now_iso
from mosaic.core.principal import Principal
from mosaic.core.settings import SettingError, preset
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.models_control import UsageRecord


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    provider: str
    model: str
    message: str
    latency_ms: int = 0
    cost_usd: float = 0.0


def model_for(config: ConfigService, principal: Principal, provider: str) -> str:
    """The model configured for the first capability using ``provider``, else its default."""
    for status in config.providers(principal).values():
        if status.choice.provider == provider:
            return status.choice.model
    try:
        return preset(provider)["vision"]
    except SettingError:
        return "fake-1"


def check_provider(config: ConfigService, principal: Principal, provider: str) -> HealthResult:
    model = model_for(config, principal, provider)
    try:
        adapter = adapter_for(config, principal, provider)
    except NotConfiguredError as exc:
        return HealthResult(False, provider, model, str(exc))
    quick = getattr(adapter, "quick", None)
    if quick is not None:  # interactive check: short timeout, no retries
        adapter = quick()
    prompt = load("healthcheck", 1)
    system, user = prompt.render({})
    request = StructuredRequest(
        "healthcheck",
        "healthcheck",
        1,
        system,
        user,
        prompt.schema,
        max_tokens=1024,  # room for adaptive thinking on Sonnet/Opus 5.x
    )
    try:
        raw = adapter.complete(
            request, model, strict_schema(prompt.schema.model_json_schema()), None
        )
        prompt.schema.model_validate(json.loads(raw.text))
    except AdapterError as exc:
        return HealthResult(False, provider, model, str(exc))
    except (ValidationError, json.JSONDecodeError):
        return HealthResult(False, provider, model, "the provider answered, but not as asked")
    cost = adapter.cost_usd(model, raw.tokens_in, raw.tokens_out)
    with config.control.db.session() as s:
        s.add(
            UsageRecord(
                user_id=principal.user_id,
                project_id=None,
                job_id=None,
                task_id=None,
                capability="healthcheck",
                provider=provider,
                model=raw.model,
                tokens_in=raw.tokens_in,
                tokens_out=raw.tokens_out,
                cost_usd=cost,
                latency_ms=raw.latency_ms,
                created_at=now_iso(),
            )
        )
    return HealthResult(True, provider, raw.model, "ok", raw.latency_ms, cost)
