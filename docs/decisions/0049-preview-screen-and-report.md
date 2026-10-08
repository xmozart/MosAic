# 0049 — The preview screen (S17) and the selection report

- Status: accepted (M2 step 8c)
- Deciders: agent (autonomous; no human gate)

## Context

In M2, S17 is "player and report", while findings (the critic UI with Apply and Ignore) are M4. The mockup's right column is the findings list, and its actions include "Open storyboard" (S16, M4) and "Export…" (S19, M4).

Three questions needed answers:
- what the right column shows in M2;
- where a version's previews come from;
- how the screen gets the facts S17's EditFacts shows. Some of them, such as the photo count, need the assets' kinds.

## Decision

- **Route:** `/p/:pid/edits/:eid?v=`. Without `v` the screen shows the latest version, and the version selector sets `v`.
- **Backend: `GET /edits/{eid}` and `/versions/{v}` add two fields.**
  - `facts`:
    - duration, target and tolerance in frames at the edit's rate;
    - shots, photos and beats;
    - days used and available;
    - the AI cost of planning.
  - `renders`: that version's render rows, newest first. They use the same rows and states as S20 (ADR 0047), and render rows now carry a cover frame.
- **The player:**
  - It plays the version's newest preview file, served with Range requests.
  - The bar shows the beats as coloured stretches. They use the categorical `cam-1…6` series in beat order (DESIGN_TOKENS), and the bar draws from the edit's known length before the video loads.
  - Chips over the picture show "v3 · preview 720p" and the current "Beat: …".
  - The version selector sits at the end of the control row, as in the mockup.
  - Positions are the timeline's integer frames, converted exactly to the player's time (`ticks = frames`, `tb = 1/rate`), so a seek lands on that frame.
- **Previews start on their own.** Opening a version that has no preview starts one, once per version per visit; it costs no AI.
  - While it renders, the picture shows "Rendering preview… n %" with a bar.
  - A failed or missing preview offers "Render again".
- **Actions:**
  - "Open storyboard" is shown, disabled, until M4.
  - "Export…" becomes **Exports**, which opens S20. S19's options are M4, and the edit's shape and resolution come from its request (ADR 0046).
  - **Render final** starts a final render. While it runs, the button reads "Rendering final…" with the status beside it. When it is done, it becomes **Download final**.
- **The right column is the selection report:** "Why these shots", with three tabs.
  - **Shots:** each shot's timecode, role, beat, reason, file and description. Clicking the timecode seeks the player, which is S17's acceptance criterion, and focuses it.
  - **Not used:** selections and alternatives that did not make the cut, with the editor's reason.
  - **Rejected:** rejections follow ADR 0042, with the AI-vs-you chip. Whole-clip rejections are tagged "Whole clip" in the `user` style. The list pages with "Show more".
  - Findings, with Apply all and Ignore all, replace or join this column in M4.
- **States:**
  - loading;
  - still being made (n %), from the edit card's job;
  - couldn't create, with the error and "Try again", which regenerates;
  - not found.
- **A preview deleted in S20 is made again** the next time its version opens. A preview is a derived output, and S17 needs one to play.
- **The page's own header** ("‹ Edits · name") stands in for the mockup's top-bar breadcrumb ("trip / name · v3"). ProjectHeader is shared by every project screen and has no breadcrumb slot. The version shows on the picture and in the selector.
- **The edit's status** (generating, failed, new) comes from the S13 edit cards, which load up to 200 edits. M4's draft endpoint should carry the status itself, so that very large projects don't depend on the list.
- **Light theme:** the picture is dark in both themes, because footage is not themed. `bg-black` was never a token, so the Player and S11's photo frame now use a dark-scoped `bg-bg`.

## Consequences

- From S13, opening an edit plays it within the time a preview render takes, with no extra click.
- The report screen and `mosaic report` read the same `GET /edits/{eid}/report`.
- M4's findings can reuse the player's `markers` (kind `finding`) and the column, without changing the route.
