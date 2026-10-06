"""The one path for structured AI calls (ARCHITECTURE.md §11, invariants 5, 6, 9).

``AIClient.structured``:

1. resolves the capability's provider and model from the provider profile;
2. renders the versioned prompt and computes a cache key from provider, model, prompt
   version, rendered text, image digests and schema — an identical request is answered
   from the artifact cache with **zero** provider calls (M0 acceptance 5);
3. reserves the estimated cost against the job's cost limit before calling; if the limit
   would be exceeded the job is paused (``paused_cost_limit``) and the task deferred;
4. validates the answer with the prompt's Pydantic schema and the caller's ``validate``
   check (rules a schema cannot express, such as "every segment answered exactly once"),
   retries once with the errors, then fails the task — never partially accepted;
5. records usage (control DB) and provenance (project DB) with tokens and cost.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from mosaic.ai import ratelimit
from mosaic.ai.adapters.base import Adapter, strict_schema
from mosaic.ai.prompts.loader import load
from mosaic.ai.registry import adapter_for
from mosaic.ai.types import AdapterError, ImageInput, StructuredRequest, UnknownPriceError
from mosaic.core.clock import now_iso
from mosaic.core.keys import artifact_key, digest
from mosaic.core.principal import Principal
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import DeferTask, PermanentError
from mosaic.storage import provenance
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import Job, UsageRecord

AI_CACHE_VERSION = "ai-cache/1"

Validator = Callable[[Any], list[str]]
"""Extra checks on a schema-valid answer; returns error messages (empty when valid)."""


@dataclass(frozen=True)
class AIResult:
    data: BaseModel
    provenance_id: int
    cached: bool
    cost_usd: float
    model: str
    provider: str


class AIClient:
    def __init__(self, ctx: TaskContext) -> None:
        if ctx.control is None:
            raise RuntimeError("AI calls need the control DB (run inside a worker)")
        self.ctx = ctx
        self.control: ControlDB = ctx.control
        self.config = ConfigService(self.control)
        job = ctx.store.job(ctx.task.job_id)
        self.principal = Principal(user_id=job.user_id) if job else self.control.local_principal

    def structured(
        self,
        capability: str,
        prompt_name: str,
        version: int,
        context: dict[str, Any],
        images: Sequence[ImageInput] = (),
        *,
        max_tokens: int = 4096,
        variant: int = 0,
        validate: Validator | None = None,
    ) -> AIResult:
        choice = self.config.provider(self.principal, capability)
        prompt = load(prompt_name, version)
        system, user = prompt.render(context)
        request = StructuredRequest(
            capability,
            prompt_name,
            version,
            system,
            user,
            prompt.schema,
            tuple(images),
            max_tokens,
            context,
        )
        schema_json = strict_schema(prompt.schema.model_json_schema())
        key = artifact_key(
            "ai",
            project_id=self.ctx.project.id,
            inputs={
                "capability": capability,
                "prompt": [prompt_name, version],
                "system": digest(system),
                "user": digest(user),
                "images": [digest(img.data.hex(), 24) for img in images],
                "schema": digest(schema_json),
                "variant": variant,
            },
            config={"provider": choice.provider, "model": choice.model},
            version=AI_CACHE_VERSION,
        )
        store = self.ctx.project.artifacts
        # A cached answer passed ``validate`` when it was stored; the rendered prompt
        # (which carries everything a validator checks against) is part of the key.
        if store.exists("ai", key):
            cached = store.get_json("ai", key)
            return AIResult(
                prompt.schema.model_validate(cached["response"]),
                store.provenance_id("ai", key),
                True,
                0.0,
                cached["model"],
                choice.provider,
            )
        # Only a cache miss needs the adapter (and therefore a key and local_only off).
        try:
            adapter = adapter_for(self.config, self.principal, choice.provider)
        except NotConfiguredError as exc:
            raise PermanentError(str(exc)) from exc
        return self._call(
            adapter, request, choice.provider, choice.model, schema_json, key, validate
        )

    # ------------------------------------------------------------------ calls

    def _reserve(self, adapter: Adapter, request: StructuredRequest, model: str) -> float:
        est_in, est_out = adapter.estimate_tokens(request)
        try:
            estimate = adapter.cost_usd(model, est_in, est_out)
        except UnknownPriceError as exc:
            raise PermanentError(str(exc)) from exc
        job_id = self.ctx.task.job_id
        if not self.ctx.store.reserve_cost(job_id, estimate):
            self.ctx.store.pause(job_id, cost_limit=True)
            raise DeferTask("AI cost limit reached for this job; raise the limit and resume")
        return estimate

    def _record_usage(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        latency_ms: int,
        capability: str,
    ) -> None:
        with self.control.db.session() as s:
            s.add(
                UsageRecord(
                    user_id=self.principal.user_id,
                    project_id=self.ctx.project.id,
                    job_id=self.ctx.task.job_id,
                    task_id=self.ctx.task.id,
                    capability=capability,
                    provider=provider,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    created_at=now_iso(),
                )
            )

    def _call(
        self,
        adapter: Adapter,
        request: StructuredRequest,
        provider: str,
        model: str,
        schema_json: dict[str, Any],
        key: str,
        validate: Validator | None,
    ) -> AIResult:
        feedback: str | None = None
        limit = ratelimit.limit_for(self.config, self.principal, provider)
        total_in = total_out = 0
        total_cost = 0.0
        served = model
        for attempt in (1, 2):
            reserved = self._reserve(adapter, request, model)
            try:
                with ratelimit.slot(
                    provider, limit, sum(adapter.estimate_tokens(request)), self.ctx.check_cancelled
                ):
                    raw = adapter.complete(request, model, schema_json, feedback)
            except AdapterError as exc:
                self.ctx.store.adjust_cost(self.ctx.task.job_id, -reserved)
                if exc.retryable:
                    raise RuntimeError(str(exc)) from None  # the worker retries the task
                raise PermanentError(str(exc)) from None
            except BaseException:  # any other failure, including a cancelled slot wait
                self.ctx.store.adjust_cost(self.ctx.task.job_id, -reserved)
                raise
            cost = adapter.cost_usd(model, raw.tokens_in, raw.tokens_out)
            self.ctx.store.adjust_cost(self.ctx.task.job_id, cost - reserved)
            self._record_usage(
                provider,
                raw.model,
                raw.tokens_in,
                raw.tokens_out,
                cost,
                raw.latency_ms,
                request.capability,
            )
            total_in += raw.tokens_in
            total_out += raw.tokens_out
            total_cost += cost
            served = raw.model
            try:
                data = request.schema.model_validate(json.loads(raw.text))
                errors = validate(data) if validate else []
            except (ValidationError, json.JSONDecodeError) as exc:
                errors = [str(exc)]
            if not errors:
                break
            feedback = "\n".join(errors)[:4000]
            if attempt == 2:
                raise PermanentError(
                    f"{request.prompt_name}/v{request.prompt_version}: invalid output "
                    f"after retry: {feedback[:500]}"
                )
        with self.ctx.write() as s:
            prov = provenance.record(
                s,
                provenance.ProvenanceInfo(
                    kind=f"ai.{request.capability}",
                    provider=provider,
                    model=served,
                    model_version=served,
                    prompt_version=f"{request.prompt_name}/v{request.prompt_version}",
                    input_keys=[key],
                    tokens_in=total_in,
                    tokens_out=total_out,
                    cost_usd=total_cost,
                ),
            )
        self.ctx.project.artifacts.put_json(
            "ai",
            key,
            {"response": data.model_dump(mode="json"), "model": served},
            provenance_id=prov,
        )
        return AIResult(data, prov, False, total_cost, served, provider)


def job_cost(control: ControlDB, job_id: int) -> float:
    with control.db.session() as s:
        job = s.get(Job, job_id)
        return float(job.cost_usd) if job else 0.0
