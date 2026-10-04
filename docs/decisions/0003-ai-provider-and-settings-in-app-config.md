# ADR 0003 — AI provider, credentials and eval corpus live in the app configuration

- **Status:** accepted by the owner (2026-10-04). Supersedes the `ANTHROPIC_API_KEY` env-var rule in `AGENT_WORKFLOW.md` §4 and the "`EVAL_CORPUS_DIR` is set in the owner's shell" part of ADR 0002 item A.
- **Context:** The spec required `ANTHROPIC_API_KEY` and `EVAL_CORPUS_DIR` as shell environment variables. The owner wants these settings in MosAic's own application configuration. The owner may also use an AI provider other than Anthropic, so the provider must be a setting. The owner will supply the values later, only when they are needed.

## Decision

1. **The provider is a setting, not a dependency.** The provider and model for each AI capability (`VisionAnalyzer`, `StoryPlanner`, `ShotSelector`, `Critic`) live in the control DB's `provider_profile` table: capability → provider, model, mode. Anthropic is the default provider, not a requirement.
   - Default models when the provider is Anthropic: Claude Haiku 4.5 for vision; Claude Sonnet 5.5 for the planner, selector, critic and Thorough L3 review; temperature 0.
   - Prompts (`ai/prompts/<name>/v<N>.md`) and their Pydantic schemas are provider-neutral. Only `ai/adapters/<provider>/` may import a provider SDK. Each adapter declares its limits and cost table (`ARCHITECTURE.md` §11). Budgets are enforced in USD from those cost tables, whatever the provider.
   - The interface and a provider registry exist from M0. M0 ships the **fake/replay** adapter and the **Anthropic** adapter. If the owner picks a provider that has no adapter yet, the agent builds that adapter at that point. This is in scope and needs no further gate, as long as its SDK passes the licensing rules. A provider is usable only if it supports image input and structured (JSON-schema or tool) output; otherwise the agent says so at the gate.
2. **Secrets live in the OS secret store.** On the dev Mac and on the desktop app, the key is stored with Python `keyring` (macOS Keychain). The control DB holds only a `secret_ref` such as `keyring:mosaic/ai/<provider>`. Server deployments (M2) keep the options in `ARCHITECTURE.md` §3: Docker secrets, or an encrypted file keyed by an install master key. `env:` refs stay supported for server and CI deployments only and are never the dev or desktop default. Invariant 11 is unchanged.
3. **The eval corpus path is a setting.** `eval.corpus_dir` is stored in the control DB's `user_preferences` table. `make eval` reads it from there. The `EVAL_CORPUS_DIR` env var is no longer required, but may override the setting for CI.
4. **How the owner enters values before the UI exists (M0–M1)**, using the `mosaic config` CLI:
   - `mosaic config show`: provider per capability, `configured` or `missing` for each key (last 4 characters only), and the corpus path.
   - `mosaic config ai set --capability <cap|all> --provider <name> --model <id>`
   - `mosaic config ai set-key --provider <name>`: reads the key from a hidden prompt or stdin, **never from argv**, and stores it in the keyring.
   - `mosaic config ai test [--provider <name>]`: validates the key with one minimal call.
   - `mosaic config set eval.corpus_dir <path>`
   
   The CLI and the later UI (S1 first run, S22 app settings) use the same service and the same `/providers` and `/secrets/*` API.
5. **Values are requested only when they are needed.** All tests and CI use the fake/replay adapter and need no configuration. The agent raises gate G1 only when the next step actually requires a real AI call or the real corpus (normally `make eval` at M0 step 12). By then all other work must be finished. The G1 request lists the exact `mosaic config` commands for the owner to run. The agent never asks for a key in chat, in a file or on a command line, and never writes one anywhere itself.

## Consequences

- M0 adds the `mosaic config` CLI, the `provider_profile`, `secret_ref` and `user_preferences` tables in the control DB, `keyring` as a dependency (MIT; recorded in `LICENSES.md`), and these tests:
  - a missing configuration gives a clear "not configured: run `mosaic config …`" error, never a crash
  - after `set-key`, the key appears in no file, DB row, log or process argv
  - switching the provider for a capability changes the adapter used, and changes the cache key so earlier cached output is not reused
- The provider and model enter the provenance and cache key (already required by `ARCHITECTURE.md` §5.3).
- S1 and S22 gain a provider selector, with one `SecretField` per configured provider.
- Affected docs: `AGENT_WORKFLOW.md`, `ARCHITECTURE.md` §3 and §11, `EVALUATION.md` §1, `milestones/M0.md`, `STATUS.md`, `ui/screens/S01-first-run.md`, `ui/screens/S22-app-settings.md`, `README.md`, `CLAUDE.md`, ADR 0002 (status note).
