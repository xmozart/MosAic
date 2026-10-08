# 0048 — The Edits screen and the basic create-edit wizard

- Status: accepted (M2 step 8b)
- Deciders: agent (autonomous; no human gate)

## Context

M2 builds S13 Edits and S14 steps 1, 2 and 6 ("basic"). The rest of the wizard, the storyboard (S16) and the creating screen (S15) are M4. The mockups show some things the M2 request cannot express yet:
- weights (step 3), pace and transitions (step 4) and sound (step 5);
- the arc template and custom beats under step 2's More options;
- saved presets, locked shots and must-include chips;
- the S15 creating screen that follows Create.

## Decision

- **Routes.**
  - S13 is `/p/:pid/edits` and S14 is `/p/:pid/edits/new`.
  - A card opens `/p/:pid/edits/:eid`, which is S17 in step 8c.
  - Create goes back to S13, where the new card shows "Generating… n %" with a ring. S15 is M4.
- **Steps 3–5** appear in the step nav but are disabled. A note under the steps says they arrive in a later update. The request keeps its defaults: balanced pace, no weights, no sound settings. Next on step 2 goes to step 6.
- **Step 1:**
  - The duration chips match the mockup. Custom takes whole seconds, from 5 to 14,400.
  - "Strict length" sets `tolerance_pct` to 0. Otherwise the tolerance is the request's 5 %, shown in seconds ("Otherwise ±15 s").
  - The AspectPicker offers the five aspects of ADR 0046. "Native" is shown disabled.
  - More options holds the final resolution (720p, 1080p, 1440p, 4K) and the frame rate (Native or the PRODUCT.md list).
- **Step 2:**
  - Seven featured StoryPresetCards with collages of the owner's own frames (ADR 0047).
  - **Custom** reveals the other nine presets as chips, with their descriptions. There is no free-form story value; free text belongs in step 6.
  - Chronology is a segmented control. The arc template and beats wait for M4.
- **Step 6:** the instructions textarea, up to 2,000 characters.
  - The idea chips are generic ("Avoid long driving clips", "End on the best sunset", "Include funny reactions", "Open with an aerial shot") and never name a place or a person (invariant 16).
  - A chip appends its sentence once.
- **The summary panel is one pure function of the request** (`summaryLines`), as S14's acceptance asks. It shows length and story, format, chronology, pace, and the length rule, plus notes when there are any.
  - **The title** is the edit's default name, made from the trip's name, the length and a short story word ("Costa Rica — 5 min cinematic"). It is sent as the edit's name.
  - **Warnings:**
    - "Your usable footage adds up to about m:ss — shorter than …" when retrieval cannot fill the length;
    - "Nothing to edit yet" with no candidates. This also disables Create.
  - Locks, must-include chips and the infeasible-locks warning are M4: M2 has no locks in the request.
- **The estimate** is `POST /edits/estimate`, debounced to one call per 400 ms pause. It reads "About 3 min · ~$0.25–0.55", or "A few seconds · no AI cost" when the plan is reused.
  - Until the estimate for the current request arrives, the previous one is shown dimmed (`aria-busy`).
  - A running analysis shows S14's banner: "Analysis is n % done…", with "Create now (preliminary)" and "Wait". Wait opens S9.
- **Keyboard:** ⌘Enter creates, but never while Create is disabled. ⌘↑ and ⌘↓ move between the open steps. The arrow keys move the choice within each radio group: lengths, shapes and stories.
- **S13:**
  - Cards follow COMPONENTS.md EditCard. A 9:16, 4:5 or 1:1 edit's cover is shown in its own shape, centred.
  - Status words:
    - "Generating… n %"
    - "Couldn't create"
    - "Waiting to start"
    - "Rendering preview…"
    - "Preview ready"
    - "Final rendered"
    - "Ready"
    - "Preliminary" (with a MAYBE-coloured dot) in place of "Ready" or "Preview ready" when the version was made during analysis, as in the mockup, together with the card's "Made before analysis finished" line
  - The list polls every 2 s while an edit is generating or rendering, but not while it is "new". An edit whose job was cancelled before it ran stays new and is not polled.
  - **"Start from" chips:**
    - "Duplicate “newest” as 90 s / 3 min";
    - "Vertical version of “newest landscape edit”".
    - Each opens the wizard prefilled through `?from=&duration=` or `?from=&aspect=9:16`.
    - Unlike the mockup ("Duplicate “5 min cinematic” as 90 s", "Vertical version of the reel"), the chips quote the edit's full name. The product cannot know which word of a name the owner thinks of as short.
    - The wizard waits, with a skeleton, until the source edit's request is in, so a late prefill never overwrites a choice. An unknown `?aspect=` is ignored.
    - "Saved preset" waits for M4, which stores presets.

## Consequences

- Making an edit from the browser now takes three steps and one click.
- When M4 adds steps 3–5, the request gains their fields and `summaryLines` grows with them.
- A vertical version made from a chip reuses the source edit's plan, at no AI cost (ADR 0046).
