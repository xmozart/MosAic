# 0073 — Planner and selector v3: the M4 request in the prompts

- Status: accepted (M4 step 5b)
- Deciders: agent (autonomous; no human gate)

## Context

ADR 0066 added the wizard's full request: arc and custom beats, content weights, editing rules, audio options and shot lengths. ADR 0072 made weights steer retrieval. The planner (v2) and selector (v2) prompts still saw only the story, chronology, pace, duration and the trip context. PRODUCT.md §4 asks for edits shaped by all of it. The M4 plan lists itinerary beats and must-include/avoid here too. The trip context already reaches both prompts with its days and places, must-include and avoid (M1).

## Decision

- **New prompt versions, planner v3 and selector v3.** Their output schemas are v2's, re-exported, so no decision shape changes (invariant 5).
- **Planner v3 gains:**
  - `arc`: a template sentence (classic travel, fast highlight, documentary), or the owner's own beats, listed in order;
  - `preferences`;
  - categories on each clip line;
  - three rules:
    - follow the arc, and with custom beats plan exactly those beats, in order, titled as given;
    - when the trip context lists days with places and the chronology is strict or mostly, let the beats follow those days;
    - follow the preferences.
- **Selector v3 gains** `preferences` and categories in each pool line, with a rule to follow them.
- **`preferences` is the request in words**, built by code, never by the AI:
  - the content weights by strength ("Strongly prefer: wildlife." … "Avoid: selfies.");
  - the editing rules that are on, including which way unique-versus-quality goes;
  - the sound choices;
  - the advanced shot lengths in seconds (display), with PRODUCT.md's exceptions: dialogue, reactions and hero shots may run longer.
- **Custom beats are enforced.** `check_plan` refuses a plan whose beat titles are not the owner's, in order (case aside). The model is asked again with the error, then the task fails (invariant 6).
  - The plan then takes the owner's titles exactly as typed (user decisions override AI).
  - Planner v3 plans exactly as many beats as the owner listed, up to 12.
  - A custom arc's beats are now 2 to 12, each 2 to 60 characters: the planner schema's own bounds for beats and titles. ADR 0066 is amended. A request saved with one beat, or with a title outside those bounds, no longer validates. This is accepted: the arc fields were added this same day in M4 step 1, and no UI can make such a request yet.
- **`EDIT_VERSION` is `edit/2`.** An edit generated again after this step plans with v3, and gets a new key and a new version.
  - Locks, drafts and regeneration (ADRs 0067–0071) use the same constants, so every AI path now plans with the M4 request.
  - `reselect` v1 (one beat, ADR 0069) still sees the request summary only, though its clip lines now carry categories too (`Candidate.line`). It will gain the preferences when "stronger opening" and "different ending" add a directive to it (M4 step 4c).
  - The edit estimate (S14) shows an edit made before this step as needing AI again. That is correct: its next generation plans with v3.
- **Transitions, photo share, loudness and music are not in the prompts.** They are timeline and render choices: M4 steps 6, 8 and 9 act on them in code.

## Consequences

- `make ci` checks with the fake adapter that:
  - the owner's beats become the edit's beats;
  - an avoided category stays out;
  - both prompts carry the preferences.
- How well a real model follows the preferences is measured at G6 with the benchmark request (M4 acceptance 1).
