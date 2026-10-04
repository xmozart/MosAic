# Autonomous Development Protocol

MosAic is built by Claude Code working autonomously across milestones. The owner (Michael) is **not** reviewing each step. You decide, record, verify and continue. You stop only at the human gates in §3.

## 1. The loop

For each milestone, in order (M0 → M1 → M2 → M3 → M4):

1. **Plan.** Break the milestone into steps (typically 8–15). Write the plan into `docs/STATUS.md` under the milestone heading. Do not wait for approval.
2. **Implement one step at a time.** For each step:
   - write the code and tests together
   - run `make check` (lint, types, unit tests) and the relevant integration tests
   - run the **spec-reviewer** subagent on the step's diff (`.claude/agents/spec-reviewer.md`) and fix what it finds
   - commit with a message `M<n>.<step>: <summary>`
   - append a one-line entry to `docs/STATUS.md`
3. **Decide, don't ask.** When the spec is ambiguous, contradictory or wrong:
   - pick the option most consistent with `CLAUDE.md` invariants and the milestone goal
   - write an ADR (`docs/decisions/NNNN-title.md`: context, options, decision, consequences)
   - update the affected doc
   - continue
4. **Park non-blocking questions.** Anything the owner should eventually weigh in on, but that has a reasonable default, goes in `docs/OPEN_QUESTIONS.md` with the default you used. Continue.
5. **Close the milestone.**
   - run the full acceptance suite
   - write `docs/reports/M<n>.md`: what was built, acceptance results, metrics, ADRs, open questions, known gaps
   - if the milestone ends at a human gate, stop there; otherwise continue straight into the next milestone

## 2. Self-sufficiency rules

- **Fix it yourself.** Fix failing tests, broken builds and tool problems yourself. Try at least three materially different approaches before treating something as blocked.
- **Pre-authorized installs and network.** You may install the dev tools the plan needs: Homebrew packages for the LGPL FFmpeg build (`nasm`, `pkg-config`, `zimg`, `openh264`, `cmake`, `meson`, `ninja`), Python packages via `uv`, Node packages via `pnpm`, and model weights from Hugging Face. Network access for these downloads is allowed.
- **Pre-authorized writes.** You may write inside the repo; inside the OS app-data directory for MosAic; and inside each trip folder under the eval corpus folder (app setting `eval.corpus_dir`, ADR 0003), limited to `.mosaic-project.json` and the `MosAic/` folder. Source media files are never modified, moved or deleted.
- **Use the fake/replay AI adapter** for all tests and CI. Real AI calls (to whichever provider is configured) happen only in `make eval`, and only within the budget (§4).
- **Keep the resume handoff current.** Keep `docs/STATUS.md` accurate enough that a fresh session can resume from it alone. Context windows end; the repo is the memory. When resuming, read `CLAUDE.md`, `docs/AGENT_WORKFLOW.md` and `docs/STATUS.md`, then continue from the first unfinished step.
- **Never weaken tests.** Never weaken, skip or delete a failing test to make progress. If a test is wrong, fix the test and record why in the commit message (and an ADR if the spec's intent changes).
- **Git remote.** Commit locally. If a git remote exists, push after each milestone; if none exists, don't create one. Mirror the CI workflow locally as `make ci`. A missing remote is not a blocker.

## 3. Human gates (the only reasons to stop)

Stop, write the request at the top of `docs/STATUS.md` under **⚠ Waiting for owner**, and end the session with a short message that says exactly what is needed.

| # | Gate | When |
|---|---|---|
| G1 | **Credentials or paid accounts** you don't have. Examples: AI provider, model or key not configured, eval corpus path not set (ADR 0003), an Apple Developer ID for signing. | Only when the next step actually needs it. First finish all other work that doesn't depend on it. List the exact `mosaic config` commands for the owner to run; never ask for a key in chat or a file. |
| G2 | **Budget.** A real-AI run would exceed the per-run or per-milestone budget. | Before the call. |
| G3 | **Destructive or out-of-bounds actions.** Deleting or modifying anything outside the pre-authorized write areas; any action on source media. | Never perform these; ask. |
| G4 | **Licensing that rules can't resolve.** A required dependency is GPL, AGPL or non-commercial with no viable alternative. | After trying alternatives. |
| G5 | **Product-visible spec change.** A change that alters what the owner sees or can do versus `docs/PRODUCT.md`/`docs/ui/`, or that breaks a `CLAUDE.md` invariant. ADR-able implementation choices do **not** qualify. | When the conflict is found. Continue other work meanwhile. |
| G6 | **Milestone quality review.** Only at the end of M0, M2 and M4. M0 and M4: the owner watches the real-footage edits and scores the rubric. M2: the owner tries the web UI. | After the milestone report is written. |
| G7 | **Hard blocker.** The same blocker persists after three materially different approaches. | After the third attempt. |

At a gate, batch everything: one message listing all needed inputs, plus `docs/OPEN_QUESTIONS.md` items that are now worth answering. Never stop for anything not in this table.

## 4. Budgets and defaults (owner-approved)

| Item | Value |
|---|---|
| Real-AI budget per `make eval` run | **$5** |
| Real-AI budget per milestone | **$25** |
| AI provider | A setting per capability in the app configuration (ADR 0003). Default: Anthropic. |
| Vision model (L2), default | Claude Haiku 4.5, temperature 0 |
| Planner, selector, critic, default | Claude Sonnet 5.5, temperature 0 |
| Thorough L3 review (M1+), default | Claude Sonnet 5.5 |
| API key | Entered by the owner with `mosaic config ai set-key` and stored in the OS keyring; the config stores only `secret_ref = keyring:mosaic/ai/<provider>`. Never an env var in dev. |
| Eval corpus | App setting `eval.corpus_dir` (`mosaic config set eval.corpus_dir <path>`) |

Providers and models are configuration, not code. Shipped defaults live in one defaults file; the owner's choices live in the control DB (`provider_profile`).

## 5. Status files

- **`docs/STATUS.md`:**
  - current milestone and step
  - the per-milestone step plan with checkboxes
  - a dated log of one line per commit
  - the **⚠ Waiting for owner** section (empty unless at a gate)
- **`docs/OPEN_QUESTIONS.md`:** each entry is `Q-<n> · <question> · default used · impact if the default is wrong`.
- **`docs/reports/M<n>.md`:** the milestone report.
