# ADR 0021 — Hierarchical summaries

- **Status:** accepted (agent decision, M1 step 5)
- **Date:** 2026-10-05

## Context

ARCHITECTURE.md §8 stage 14 lists summaries shot → scene → day → trip, "cheap to
regenerate when context changes". PRODUCT.md §3 and S7 require that changing the trip
context re-runs only summary and labelling tasks. §17 requires that no AI call receives
the whole library. Several things were left open: what a "scene" is, which levels use AI,
and which model writes them.

## Decision

- **Levels**, stored in the `summary` table, with one row per (level, ref):
  - `shot` (ref = shot id) and `scene` (one recording; ref = asset id) are **composed
    from the observations**, with no AI. The L3 review is preferred over L2 vision.
    REJECT segments are left out. The text is the descriptions of the most interesting
    clips, in time order. The row also stores the top subjects and up to three highlight
    clips. These rows are rebuilt on every run, asset by asset, and rows for removed
    shots or recordings are deleted. A "scene" is a recording: shots inside a recording
    are already the finer level, and grouping recordings into scenes adds nothing that
    the day call does not already do.
  - `day` (ref = trip day as numbered by the editor; 0 = undated) and `trip` (ref = 0)
    are written by a new **`summarizer`** capability. It defaults to Haiku 4.5: the input
    is short text, so an economical model is enough. Presets: Haiku for `anthropic` and
    `claude-cli`, gpt-5.5 for `codex-cli`. Like `reviewer`, it is a later capability and
    inherits a single owner provider choice (ADR 0019).
- **Bounded input.**
  - A day call sees one line per recording: start time, asset, length, composed text,
    subjects and highlight clips. At most 80 lines; beyond that, the most interesting are
    kept, in time order.
  - The trip call sees one line per day, with that day's highlights.
  - Each answer gives a summary, up to six themes and up to eight highlights. The
    highlights are validated against the references in the notes, and an invalid
    reference is retried with the error (invariant 6).
  - Names only come from the trip context (invariant 16, as in the review prompt).
- **Keys.** A day or trip summary is keyed on a digest of its input lines, the context
  digest, the provider and model, and the prompt and algorithm versions. An unchanged key
  means no call. The AI client cache also deduplicates.
- **When it runs.**
  - `summaries` is an L2 project stage after dispositions, so it is skipped in a Custom
    run without L2.
  - A deepen job appends it after its dispositions, because reviews change descriptions
    and interest.
  - Saving the trip context (API `PUT /trip-context`, CLI `mosaic context set|parse|clear`)
    submits a job with only the summaries task.
  - With no summarizer configured, the day and trip summaries are skipped with a reason;
    shot and scene summaries are still written.
- **Summaries come last.** The project stage is registered after `deep review`, so a
  summarizer failure (provider error, cost limit, invalid output) never cancels an
  analysis stage. In Thorough, the project stage skips itself: the deep review chain
  ends with a summaries task over the reviewed clips, so nothing is asked twice. When
  there is nothing to review, the chain is just that summaries task.
- **Acceptance 5 counts footage-analysis calls.** M1 acceptance 5 ("new AI calls equal
  the L3 candidate count") is read as vision and review calls. The summaries refresh at
  the end of a deepen job adds text calls: one per day whose input changed, plus the
  trip. The test asserts both counts separately.
- **Day numbering, scale and superseded runs.**
  - Days are numbered from all video assets, exactly as retrieval and deepen number
    them.
  - Only the day and trip keys are loaded.
  - Scene and shot summaries are paged in the API (`after_ref`, `limit`) and streamed in
    the CLI.
  - A day or trip answer is not stored if the trip context changed while it ran: that
    save started a newer run.
  - The day label (which carries its date) is part of the key.
- **Not yet consumed by the planner.** Feeding summaries into planner prompts is a prompt
  change that needs an eval (EVALUATION §4). It is planned with the M1 acceptance eval
  (step 14) or M2 story work, not done silently here.
- **The eval does not require the summarizer.** The eval metrics do not read summaries,
  so an unconfigured summarizer skips its task and does not stop the eval at G1.

## Consequences

- S7's acceptance holds: the context-change test asserts that the job has only the
  summaries task, and that the only AI calls are one per day plus one for the trip.
- The UI can show day and trip summaries (`GET /projects/{pid}/summaries`) and the CLI
  prints them (`mosaic summary`).
