# 0040 — Inventory, clock check and trip context screens

- Status: accepted (M2 step 5d)
- Deciders: agent (autonomous; no human gate)

## Context

S5, S6 and S7 complete the journey from opening a folder to setting up analysis. Building them raised six questions the specs leave open:

- **Camera colours.** The S5 trip timeline gives each camera a colour. The mockup uses a purple that is not a token, and it draws cameras with `use`, `maybe` and `info`. Those tokens name dispositions and notices. Using them for cameras would tie a chart to those meanings, and a later change to a disposition colour would change the chart.
- **"Show files".** The Needs-attention rows offer it, but no endpoint lists the files behind a row.
- **Evidence frames.** S6 shows an evidence pair as two frames. Suggestions stored segment ids only.
- **When clock suggestions exist.** They come from matching image embeddings (ADR 0027), which only the analysis computes. In the reference journey, S5 and S6 come before analysis.
- **Reading the parse result.** Trip-context parsing is an AI job (invariant 8). Its proposal was only on the task result, which the web client can't read.
- **Ignore and Skip.** These hide an attention row. Unreadable and cloud-only files are already left out of analysis, so these actions change nothing in the project.

## Decision

- **Camera series tokens.** `cam-1` … `cam-6` are added to `tokens.json`, for dark and light themes.
  - The dark values deliberately repeat the approved mockup's timeline, so some equal `accent`, `info`, `use` and `maybe` today.
  - They are separate tokens so the two meanings can diverge without touching either.
  - They are only for telling cameras apart in charts, and a chart always names the camera next to its colour, in a legend or a label (DESIGN_TOKENS.md).
  - The timeline sits apart from any disposition UI.
- **`GET /projects/{pid}/inventory/files`** lists the files behind one row:
  - `kind` is unreadable, limited or cloud;
  - an unreadable row passes its `group` (a representative asset id, the same reason);
  - paths are relative to the project folder, so a server never shows host paths;
  - results are paged by media file id.

  The inventory adds `limited` per camera, so a card can say "41 clips (14 are 360°)". An unreadable row of one file names it (`example`).
- **Evidence pairs carry frame ids.** Each pair has `device_sample` and `reference_sample`: the first sample frame inside the segment, else the nearest one of its shot, else of its clip.
- **Before analysis, S6 is manual only.** Cameras without a suggestion get the stepper with Adjust / Leave and the line "No suggestion yet: cameras are compared during analysis." S5's clock card says the same. Once analysis has run, S5 shows "Clock 5 h ahead?" on the camera and S6 shows the evidence. We did not add a metadata-only heuristic: it would guess without evidence.
- **The parse proposal is also the job's result.** S7 polls `GET /jobs/{id}` and merges `result.proposal` into what the user has, following invariant 10.
  - A parsed value fills only an empty field: trip name, a day's place.
  - A different parsed day note is appended to the user's.
  - New days, people and chips are added.
  - Nothing the user typed or saved is replaced.
  - Added values are tinted `accent-soft`.
  - Nothing is stored until Save (PUT), which re-runs summaries only.
- **Stepper keys.** On the focused stepper, `=` or numpad `+` adds 1 h and `-` subtracts 1 h. With Shift, the step is 1 min. On a US keyboard, that means the `+` key, which is Shift+`=`, steps by 1 min, and `_` subtracts 1 min. At a day or more, the value shows minutes when there are any ("+1 d 00 h 01 m"), so a fine step stays visible. Offsets are rounded to whole minutes before they are split into hours and minutes.
- **S5 and S6 word the same thing.** Both show the offset still to apply: the suggestion minus the offset already set.
- **Ignore and Skip are a per-browser display choice.** They are kept in local storage for that project. If storage is unavailable, they last for the visit. The rows come back in another browser, which is harmless.
- **Flow.** `/p/:pid` opens an analysed trip in its library, and a new one at `/p/:pid/inventory`. Continue goes to `/p/:pid/context`, and Save or Skip there goes to `/p/:pid/analyze` (S8, step 6). The clock check is a dialog over S5.
- **S6 copy.** The verdict is worded on the client from the offset still to apply ("Appears 1 day behind"). The explanation reads "These look like the same moment: N matching moments agree." We have no scene description to name the moment, and invariant 16 forbids inventing one.

## Consequences

- S21's device list can use the same series tokens.
- Clock problems show on S5 only after analysis. The S5 and S6 entry points stay useful for setting a clock by hand before then.
- A later milestone may persist Ignore per project if users ask for it. That is not needed now, because ignoring changes no analysis.
- `GET /jobs/{id}` has no per-project permission check yet; it predates this step. It now returns a parse proposal, which can include people's descriptions. Multi-user work (FUTURE_APPENDIX) must add `check()` there; this is tracked in STATUS.
