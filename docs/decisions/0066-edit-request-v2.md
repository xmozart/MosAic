# 0066 — The M4 edit request

- Status: accepted (M4 step 1)
- Deciders: agent (autonomous; no human gate)

## Context

M4 makes the whole wizard real (PRODUCT.md §4, S14): arc and custom beats, content weights, editing rules, photo share, advanced shot lengths, transitions, audio options, loudness and a music bed. Before M4, `EditRequest` held only duration, story, chronology, pace, tolerance, instructions, fps, variant, aspect and resolution. Edits saved in M2 and M3 store their request as JSON, and they must keep loading.

## Decision

- **Every new field has the wizard's default:**
  - `arc`: `classic_travel`;
  - `beats`: `[]` (a custom arc only, 2–12 beats of 2–60 characters, in order; since M4 step 5b these are the planner's own bounds, because the owner's beats become the plan's beat titles and a beat's share of the edit is at most 80 %);
  - `weights`: `{}`;
  - `rules`: avoid repetition and unique over quality on, the rest off;
  - `photo_share`: `some`;
  - `shot_lengths`: none (the pace's own);
  - `transitions`: `cuts`;
  - `audio`: keep dialogue, natural sound and reduce wind on;
  - `loudness`: `web`;
  - `music`: none.

  A saved request without them validates as before. Unknown fields are still refused (`extra="forbid"`).
- **Weights** map one of the 22 PRODUCT.md categories to `avoid | less | neutral | more | strong`. Neutral is the default and is dropped on validation, so `{people: neutral}` and `{}` are the same request with the same key.
- **Advanced shot lengths are integer tenths of a second** (`min_ds ≤ preferred_ds ≤ max_ds`; 0.3–60 s, max up to 120 s). That is how the user enters them, and it keeps the request free of float times (invariant 3). `pace_frames` turns them into frames at the timeline rate, as it does a pace.
- **Music** is the track's absolute path, a level in whole dB (−40 to 0, default −18) and fades in whole milliseconds. The track is read and never changed (invariant 1). Its path is checked where an edit is saved: it must be a readable file, and in server mode it must be under a media root (M4 step 9c). Ducking under speech is fixed in M4, and beat awareness is M6.
- **`loudness` is render-only**, like aspect and resolution. It changes the final mix, never the shots, so it is not part of the edit's key.
- **Defaults come from PRODUCT.md §4,** not from the mockup's filled-in example (which also shows 4K and a chosen track). The summary panel and Storybook use these defaults.
- **Names.** Categories are PRODUCT's, in snake case. "Activities/action" is `action`, "slow motion" is `slow_motion`, and "natural sound" is `natural_sound`. The weight "Strongly prefer" is `strong`. The wizard's labels map back one to one.
- **Rules beyond the mockup's checkboxes.** `unique_over_quality` ("unique moments over technical quality, or the reverse") and `long_holds` are PRODUCT rules that the mockup's step 4 does not show. The wizard puts them under step 4's More options.
- **Advanced shot lengths are capped by dialogue, not the other way round.** Dialogue may run to `max(20 s, max)`, so a dialogue shot is never held shorter than any other shot.
- **Transitions.** PRODUCT.md §4 and the mockup offer *Mostly cuts / Soft dissolves / Minimal*, and those are the request values. M4.md's "cuts, dissolves, dips" are what the timeline and the renderer produce:
  - **`cuts`** (the default): straight cuts, with a short dip to black only at the opening, the closing and around title cards;
  - **`dissolves`**: short dissolves where one beat changes to the next, with cuts inside beats;
  - **`minimal`**: cuts only, with no dip or dissolve anywhere.
- **Music source.** The mockup offers *None / Choose track / Choose folder*. M4 lays one user track under the edit. *Choose folder* (pick a track from a folder of music) waits for M6's music library, so the wizard shows None and Choose track only.
- **Edit keys stay stable.** The M4 fields enter `key_dump` only when they differ from their defaults. An M2 or M3 edit keeps its key, so regenerating it unchanged re-plans nothing (invariant 9).
  - `service.create_edit` compares stored requests after filling in the defaults, so re-running `mosaic edit` with the same arguments still finds the M2 edit.
  - `EDIT_VERSION` is bumped by the step that changes what a request produces (retrieval and prompts, M4 step 5), not by this one.

## Consequences

- The API still takes the request as a JSON object validated by `EditRequest`. The wizard and the summary panel build it, so S14's summary is generated from the request object, which is a single source.
- Fields that M4's later steps act on (weights, rules, photo share, transitions, audio and music) are stored and validated from now on. Until those steps land, they change only the key.
