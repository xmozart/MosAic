# 0082 — The AI critic: notes on the cut by event id, mapped to the same fixes

- Status: accepted (M4 step 10b)
- Deciders: agent (autonomous; no human gate)

## Context

M4: "The AI critic (optional) takes the EDL plus summaries and returns structured suggestions. It does not analyze the rendered video in v1." ARCHITECTURE §9 places it after the deterministic critic: "story coherence, opening/ending strength; outputs structured suggestions that re-enter at selector or solver". AI output is validated against a schema and never contains timings or media operations (invariants 5, 6); user decisions override AI (invariant 10). The `critic` capability already has a provider and model in the settings (ADR 0003).

## Decision

- **When.** After a generation is timed (`edit.generate`), when the `editing.ai_critic` setting is on (the default) and the critic's provider is ready. It is one structured call (`critic/v1`, at most 2000 output tokens) per new version made by generation; drafts saved from the storyboard and findings applied get the deterministic critic only.
- **What it reads.** The trip context, the request, the plan's beats, the cut as one line per shot (event id, start, beat, role, length, what the clip shows, interest, speech; no title cards) and what the deterministic checks already found. It never sees the video.
- **What it answers** (`critic/schema_v1.py`): up to 8 notes, each `{event_id | null, action: remove | replace | note, severity: warning | info, text}`. Event ids must be shots of this cut, and remove/replace need one; anything else is a validation error, retried with the error and then given up.
- **Fixes come from code.** "remove" becomes `remove_shot`; "replace" becomes `replace_shot` with the shot's first alternative not in the edit (a note without a fix when there is none) - the same `critic.fix_for` as the deterministic critic, so a shot the owner locked, pinned or chose never gets a fix. The notes join the version's findings as `ai_note`, `ai_remove`, `ai_replace` with `source: ai`, and are applied or ignored like any finding (ADR 0081).
- **Optional means optional.** Off, not configured (no key, local only) or answering invalidly after its retries, the version is made without it. That is invariant 6 applied to the critic's own sub-step: its answer is all or nothing, never partly accepted, and its failure fails only that sub-step. A transient provider error or the cost limit retries or defers the generation as for any AI call (the planner and selector answers come from the AI cache); `metrics.ai.critic` says which provider answered or why it was skipped. Its cost joins the version's AI cost, and the edit estimate counts its call when it is on.
- **Keys.** The critic changes no cut, so it is not part of the edit's key: a reused version keeps the findings it has.

## Consequences

- S17 shows the AI's story notes beside the checks, each applicable in one click when it maps to a fix.
- The critic runs on generations only; reviewing every manual save would cost a call per save.
