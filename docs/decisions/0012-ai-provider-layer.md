# ADR 0012 — AI provider layer: caching, budgets, per-model options, no refusal fallback

- **Status:** accepted (agent decision, M0 step 9b)
- **Date:** 2026-10-04

## Context

`ARCHITECTURE.md §11` and ADR 0003 define capabilities, adapters, structured output with
one validated retry, and budgets. Details the spec leaves open:

- Claude Sonnet 5.5 rejects non-default `temperature` and always thinks; Claude Haiku 4.5
  accepts `temperature`. `EVALUATION.md §4` asks for "temperature 0 (or the lowest the
  provider offers)".
- Current Claude models offer server-side refusal fallbacks that re-run a declined
  request on another model.
- Several AI tasks run concurrently; a check-then-call budget test can overspend.
- M0 acceptance 5: an identical `mosaic edit` makes zero AI calls.

## Decision

1. **One call path** (`ai/client.py`): provider and model from the provider profile;
   prompt from `ai/prompts/<name>/v<N>.md`; JSON schema from the prompt's Pydantic model
   (made strict: closed objects, unsupported bounds removed; Pydantic validates the full
   constraints); one retry with the validation errors; otherwise the task fails.
2. **Cache key** = provider + model + prompt name/version + digests of the rendered system
   and user text, the images and the schema + `variant`. Cached answers are artifacts with
   provenance; an identical request is answered without calling the provider.
3. **Per-model options:** `temperature: 0` where accepted (Haiku 4.5); Sonnet/Opus 5.x get
   `output_config.effort: "medium"` and default sampling.
4. **No server-side refusal fallback.** Provenance, cost and reproducibility must name the
   model that produced the answer. A refusal fails the task with its category.
5. **Budgets:** the estimated cost (adapter estimate, upper bound) is reserved atomically
   on the job (`UPDATE … WHERE cost_usd + estimate <= limit`) before each call and settled
   to the actual cost after it. If the reservation fails, the job is paused as
   `paused_cost_limit` and the task is deferred without consuming a retry. Every call is a
   `usage_record` row.
6. **Fake/replay adapter:** replays recordings keyed by request hash from
   `$MOSAIC_AI_REPLAY_DIR`, else builds a deterministic, schema-valid answer from the
   request context with a responder registered per prompt.
7. **Local models are adapters too:** faster-whisper (`Transcriber`) and SigLIP ONNX
   (`Embedder`) live in `ai/adapters/`, with models from the provider profile.

## Consequences

- Prompt changes (new version) invalidate the cache by construction.
- A Sonnet 5.5 call is not bit-for-bit repeatable; caching gives repeatability for an
  identical request.
- Rate limiting relies on the SDK's retries for now; per-provider token buckets come with
  heavier parallel use (M1).
