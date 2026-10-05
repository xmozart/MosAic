# ADR 0018 — Trip context and L3 deep review (M1 steps 1–2)

- **Status:** accepted (agent decision, M1). It follows the owner's G6 feedback: on
  Airshow, "context is probably the key"; more aircraft, the F-35 demo, fewer crowds.
- **Date:** 2026-10-05

## Context

On the real Airshow footage:
- Vision named aircraft in only 31 of 485 segments.
- The M0 edit was 14 % aircraft and 22 % crowd by time.

Two causes:
- The models did not know what the trip was about.
- In a 392 px mosaic tile from 4K footage, a fast jet is a few pixels ("blue sky with a
  tiny dark speck").

PRODUCT.md §3 says that changing the trip context re-runs only summaries and labeling,
never vision. ANALYSIS_MODES.md defines L3 as a high-resolution review of candidates
only, by a stronger model.

## Decision

1. **Trip context** has the PRODUCT §3 structure and is stored per project in
   `trip_context`. It is set with `mosaic context set|parse` or `PUT /trip-context`.
   - Parsing free text is a job, and its result is only a proposal until the owner
     confirms it.
   - It enters planner v2, selector v2 and the L3 review prompt, and later the summaries.
   - **It never enters the L2 vision prompt**, so a change cannot invalidate L2.
   - The edit key includes its digest. Place and people names may come only from the
     context or the instructions (invariant 16).
2. **L3 deep review** is `mosaic deepen [--day N] [--segment …]`, and Thorough mode in
   step 4.
   - Candidates are segments that are not an effective REJECT and are the recommended
     pick of their similarity group (or a user USE).
   - Each candidate gets 3 frames taken from the **original** files at the reviewer's
     largest useful size (1568 px for Claude), tone-mapped from HLG/PQ, and one
     `review/v1` call with the trip context. That is one AI call per candidate (M1
     acceptance 5), cached by request.
   - The result goes in `deep_review`, in the vision vocabulary. It supersedes L2 in
     dispositions, retrieval and the edit key.
   - `context_digest` records which context it saw. A later context change marks it
     stale, but nothing re-runs it automatically, because L3 costs money. The owner
     re-runs `deepen`.
3. **A new `reviewer` capability** defaults to Claude Sonnet 5.5 (AGENT_WORKFLOW §4) and is
   included in every provider preset.
4. **Raising a cost limit.**
   - CLI: `mosaic jobs resume <job> --cost-limit <usd>`.
   - API: `POST /jobs/{id}/resume {cost_limit_usd}`.
   - The new limit must be above what the job has already spent (M1 acceptance 7).

5. **What is not built yet:** the user-starred candidates and the moment detection that
   ANALYSIS_MODES lists for L3. Starring needs the rating UI (M2), and moment detection
   comes with the Thorough deepening work. A review whose context, model, files or frames
   changed is redone on the next `deepen`, because its stored key differs.

## Consequences

- **Airshow results by primary subject**, measured on the same current labels for every
  edit (the first subject of the L3 review, else of L2):

  | Edit | Aircraft | Crowd |
  |---|---|---|
  | M0 | 45 % | 29 % |
  | Context only | 69 % | 16 % |
  | Context + L3 + the narrowed "obstructed" rule | 79 % | 2 % |

  Confirmed must-exclude violations stay at 0.
- **Why primary subject.** An earlier keyword-share metric over descriptions was
  misleading. Descriptions mention everything in frame ("spectators photograph a distant
  jet"), so they over-count both subjects.
- A full Airshow deepening is about 180 reviewer calls. Through Claude Code that costs no
  API money but takes wall time. Through the API at Sonnet prices it is roughly
  $2–3 per trip.
- `context.parse` uses the `planner` capability. The summaries step may move it to a
  cheaper text capability.
