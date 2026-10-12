# 0074 — More or less of a category, a stronger opening, a different ending

- Status: accepted (M4 step 4c)
- Deciders: agent (autonomous; no human gate)

## Context

PRODUCT.md §8's last three actions are:
- more or less of a content category;
- a stronger opening;
- a different ending.

Every action creates a new version and respects locks. Content weights steer retrieval (ADR 0072) and the prompts (ADR 0073). One beat can be regenerated around its locks (ADR 0069), and the whole edit too (ADR 0070).

## Decision

- **More or less of a category is a one-step weight change, then a whole-edit regeneration.**
  - `POST /edits/{eid}/category {category, more}` moves the category's weight one step along avoid, less, neutral, more, strong.
  - It records the change as a storyboard op, `set_weight`, which is undoable like any other. The draft's request applies its weight changes (neutral resets), the same way it applies a new length (ADR 0071).
  - It then queues `edit.regenerate` with scope `all`. That job saves the draft (with the new weight) first, so the new plan and selection see it in retrieval and in the prompts. The owner's locks are carried (ADR 0070).
  - It returns 409 at either end of the scale. If the regeneration cannot be queued (the draft changed meanwhile, also a 409), the weight is put back by an op of its own, so a retry steps once. An undo is not used: it could take back the owner's change that raced in (invariant 10).
  - The edit's own request takes the new weights, as it takes a new length.
- **A stronger opening and a different ending regenerate the first or the last beat** around its locked shots (ADR 0069), with a directive: `POST /edits/{eid}/regenerate?scope=opening|ending`.
  - The new prompt `reselect` v2 adds the directive, plus the owner's preferences (ADR 0073), which v1 lacked. Its output schema is v1's.
  - The directive for the opening asks for an arresting first shot that sets the place and the mood. The one for the ending asks for an ending other than the current closing clips, on a calm, memorable moment. Code writes them, never the AI.
  - Every free slot in the reselect prompt shows the clip it holds now, so the model can do something different.
  - For the ending, the beat's current free clips also leave the pool whenever the rest can still fill its free slots. The ending is then different by construction, not only by request.
  - The first or last beat is taken when the job runs, not when it is queued, so moving beats in between still regenerates the opening or the ending. The job's `beat_id` (which `regenerating` reports) is the one at queue time, so in that race S16 may briefly mark the wrong beat as regenerating.
  - The versions read "A stronger opening" and "A different ending". `metrics.regenerated` records the directive, and the key includes it.
- **Too few clips is refused before any AI call.** A plan has at least two beats, each at most 80 % of the edit, and no clip is used twice. So with fewer than two usable clips, for example when the owner avoids nearly everything, generating or regenerating stops before any AI call with the reason, instead of paying for retries that cannot succeed.

## Consequences

- Every regeneration action in PRODUCT.md §8 exists and respects locks.
- S16's header actions and S17's findings (M4 step 10) call these endpoints.
