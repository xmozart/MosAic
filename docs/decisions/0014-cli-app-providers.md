# ADR 0014 — Claude Code and Codex apps as AI providers (no API key)

- **Status:** accepted. The owner asked for this on 2026-10-04; the agent designed it in M0 step 9d.
- **Date:** 2026-10-04

## Context

The owner wants every AI function to run through the AI apps already installed on the
machine, the Claude Code CLI (`claude`) and the Codex CLI (`codex`), using the owner's own
sign-in instead of an API key. ADR 0003 already makes the provider a per-capability
setting, so this adds providers; nothing is replaced.

Both apps were checked on the dev Mac (Claude Code 2.1.285, codex-cli 0.142.5):
- **Claude Code.** `claude -p` accepts one stream-json user message on stdin, including
  base64 image blocks. `--json-schema` makes the final `result` event carry
  `structured_output`, plus token usage.
- **Codex.** `codex exec` takes the prompt on stdin, images as files (`-i`) and a schema
  file (`--output-schema`), and writes the final message to a file (`-o`). Token usage
  arrives in `turn.completed`.
- The owner's Codex default model needs a newer Codex release, so MosAic always passes
  the model explicitly.

## Decision

1. **Two providers, `claude-cli` and `codex-cli`**, each in its own adapter folder:
   `ai/adapters/claude_cli/` and `ai/adapters/codex_cli/`. The shared subprocess helpers
   are in `ai/adapters/cli_common.py`.
   - Both serve vision, planner, selector and critic, through the same prompts, schemas,
     validation, retry and cache as every other provider (invariants 5, 6 and 9).
   - The app runs as a subprocess: no shell, a fresh empty working folder, no tools or a
     read-only sandbox, no session persistence, and no user configuration or instruction
     files (`--safe-mode`; Codex `--ignore-user-config --ignore-rules`).
   - Codex additionally gets `--disable` for every feature that gives the model a tool
     (shell, exec, browser, computer use, image generation, apps, plugins, sub-agents,
     hooks), so it can only answer. The read-only sandbox is the second line of defence.
   - User content (prompt text, trip context, images) goes through stdin and temporary
     files, never argv. Only MosAic's fixed system prompt and the schema are in argv
     (Claude), because the app has no file option for them. The prompt loader enforces
     this: placeholders are rejected in a prompt's System section, so request data can
     only appear in the User section.
   - The app paths can be changed only with `mosaic config` on the host, never through
     the HTTP settings API, so an API caller cannot choose a program for MosAic to run.
   - The HTTP key-validation route rejects these providers: they have no key, and checking
     one runs the app. `mosaic config ai test` checks them.
   - `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY` and `CODEX_API_KEY`
     are removed from the child environment, so the app always uses the signed-in
     subscription and never a key (invariant 11 holds: MosAic stores no secret).
2. **Mode `cli`.** These providers need no key. `ai.local_only` still blocks them, because
   footage descriptions and images leave the machine. Each provider checks that its app
   is present up front:
   - `ai.cli.claude_path` and `ai.cli.codex_path` hold the app's path ("" means look it
     up on PATH).
   - A missing app is "not configured", with the fix. Vision is then skipped (ADR 0013),
     not failed.
3. **Cost.** Use is billed to the owner's subscription, not per token, so the adapters
   report $0. Job cost limits and the eval dollar budgets do not constrain them. Tokens,
   latency and provenance are still recorded per call.
   - The subscription's own rate limits apply. A rate-limit message is treated as
     retryable.
   - Concurrency is bounded by the worker's `ai_api` slots.
4. **Presets.** `mosaic config ai use <anthropic|claude-cli|codex-cli>` sets all four
   capabilities in one step:
   - anthropic and claude-cli: Haiku 4.5 for vision, Sonnet 5.5 for the rest
   - codex-cli: `gpt-5.5` for all four
5. **Same sheet geometry.** Both CLIs get 1568 px sheets, the same as the Anthropic API.
   Mosaics are therefore identical across providers. The AI cache is still per provider
   and model (ADR 0012), so switching provider makes new calls.

## Consequences

- An owner with a Claude or ChatGPT subscription needs no API key. G1 for `make eval`
  becomes "choose a provider (`mosaic config ai use claude-cli`) and set
  `eval.corpus_dir`". A key is needed only for the `anthropic` provider.
- Real calls through the apps still happen only for owner-requested checks (`ai test`)
  and `make eval`. Tests drive stand-in executables, never the real apps.
- **Licensing.** The apps are installed by the user and run as separate processes. MosAic
  neither bundles nor links them (Codex CLI: Apache-2.0; Claude Code: Anthropic's
  commercial terms). `LICENSES.md` records them as optional user-installed tools.
- CLI output formats can change between app versions. The parsers accept extra fields and
  fail with a clear message. `mosaic config ai test` is the first thing to run after an
  app update.
- Each call starts a process (about 2–4 s of overhead), so a long trip's vision pass is
  slower than with the API.
