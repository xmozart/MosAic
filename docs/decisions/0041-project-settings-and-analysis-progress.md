# 0041 — Project settings, Advanced analysis, and the progress view

- Status: accepted (M2 step 6a)
- Deciders: agent (autonomous; no human gate)

## Context

- **S8 Advanced.** The S8 acceptance says "Advanced overrides are stored as project settings with source shown". `/projects/{pid}/settings` was in API_MAP for S21 but did not exist, and settings were app-wide only (S22).
- **Mismatched fields.** The Advanced grid lists fields that don't map one-to-one onto the analysis mode (ADR 0020):
  - Scene sensitivity is Low / Medium / High.
  - The scene-understanding and story models are AI provider choices (S22, ADR 0003).
  - Processing device is a hardware fact (ADR 0030).
  - The GPS toggle maps to `ai.send_gps`, which no code reads yet: no prompt sends location today.
- **Custom runs.** Custom mode was Balanced plus overrides. Overriding one value on top of Thorough would have silently dropped L3.
- **S9 needs data the API lacked:**
  - plain-word stage rows with notes ("2,380 shots", "7,440 frames → 4,120 kept");
  - the current contact sheet and its latest AI description;
  - failed clips;
  - the `analysis.ready_to_browse` event.

## Decision

- **Project settings live in the project DB.** They are stored in the `project_meta` row `settings`, so they travel with the project.
  - **Keys:**
    - `analysis.mode`, `analysis.cost_limit_usd` (falls back to `ai.budget.per_job_usd`) and `ai.send_gps` override app settings;
    - `analysis.sample_interval`, `analysis.tiles`, `analysis.forced_max_shot`, `analysis.proxy` and `analysis.stt_model` override the mode's own values.
  - **Sources:** each value reports `project`, `user`, `default` or `mode`. With `mode`, the preset decides; `?mode=` shows that preset's values.
  - **Validation:** values are checked as the mode parameters they become; PATCH with null resets a key.
- **A preset run carries the project's overrides.** `POST /analysis-runs {mode: preset}` with stored overrides runs `custom` with `base` set to that preset. A Thorough base keeps L3.
  - `ModeConfig.base` records the preset. It sets the default speed factor of estimates and the name the owner sees: the job's `preset` parameter and the "Analyzed · Thorough" status.
  - `base` is not a stage parameter, so artifact keys are unchanged (invariant 9). The key-bearing fields are what change.
  - Estimates do the same. `?overrides=` estimates S8 edits that are not saved yet, with the same checks as PATCH.
  - A run without `cost_limit` uses the project's `analysis.cost_limit_usd`, else the app budget. This applies to deepening too.
- **How S8 fills the grid:**
  - **Scene sensitivity** sets `forced_max_shot`, the longest shot before it is split: Low 120 s, Medium 60 s, High 30 s. This is the parameter that decides how finely long takes are cut.
    - It does not change the cut detector's threshold.
    - We considered adding a threshold field to `ModeConfig`, but that adds a key field and a calibration we have no evidence for. The mode's detector stays as the preset sets it.
  - **Scene-understanding and story models** show the vision and planner providers read-only, with a link to Settings. They read "Not available in Local only" when `ai.local_only` is set.
  - **Processing device** shows the hardware probe, read-only.
  - **GPS** is stored as `ai.send_gps`. Nothing sends location yet, so it changes nothing today, and the hint says location stays local.
- **`GET /projects/{pid}/analysis/progress`** returns S9's view of the latest analysis or deepening job.
  - **Steps:** the pipeline's stages are grouped under VOICE words. `visual` feeds Finding shots, Picking frames and Measuring quality, because one task does all three. Unknown stages fall under "Building your library".
  - **Notes** are counts from the project DB.
  - **Live card:** the newest described contact sheet (served by `/media/{pid}/mosaic/{id}`), one description, the file and the trip day.
  - **Failures** list file names with a short phrase ("timed out", "couldn't be read", "couldn't be processed"), never tool output.
  - **Clips** counts video assets with all per-asset tasks finished.
  - **Counted in SQL:** failures and clips are aggregated in SQL; file names are looked up for the shown page only (invariant 13).
  - **Step states:**
    - A cancelled job keeps its work, so unfinished steps show as pending: S9 "Cancelled (work kept, Resume)".
    - Only a failed job marks them failed.
    - A paused job marks them paused.
  - **Deepening jobs:** notes count the whole project, which is what the library will hold after the job.
- **`analysis.ready_to_browse`** is sent once per analysis job, when L0 and every per-asset L1 task are finished and at least one has succeeded. Project-wide stages wait for L2, so they are not part of it.
  - The same rule appears as `ready_to_browse` in the progress view, so a page opened later still knows.
  - "Once" is per event stream. A reconnect may repeat it, so clients deduplicate by `job_id`.

## Screens (step 6b)

- **S8 Advanced edits.** Edits stay local until **Analyze**. Analyze PATCHes them, together with `analysis.mode`, then starts the preset. Estimates follow unsaved edits through `?overrides=`.
  - Each field shows its source: Changed here, This project, Your preference, Default, or From the mode.
  - **Reset** on a saved project value clears it at once, so the field shows the mode's own value.
  - The GPS hint says location stays on this computer and that no analysis step uses it yet.
- **S9 type sizes.** The big percentage uses the `display` token (32 px), not the mockup's 40 px; the cost uses `subhead`. Tokens only (invariant 15).
- **S9 cancelled runs.** "Resume analysis" starts the same preset again. Artifacts are keyed, so everything finished is reused (invariant 9), and a cancelled job is never reopened.
- **S9 cost-limit pause.** It reuses the S0 cost-ceiling dialog: the new limit must exceed both the old limit and the amount spent.
- **Ready to browse.** The event also shows one toast per job anywhere in the app. S9 shows its banner from the progress view, which it polls every 2 s.
- **S9 copy that needs data the server doesn't have yet:**
  - The cost-limit banner offers **Raise limit** and **Keep paused**, where Keep paused only dismisses the notice. It leaves out S9b's "About $2.40 more to finish": no projection of the remaining cost exists yet, and invariant 16 forbids inventing one.
  - The completed card shows cost and counts, but not elapsed time, which the job does not report.
  - The ready-to-browse toast doesn't name the project: the activity stream carries ids, not names.
- **S9 deepening jobs.** The card is labelled "Deepening · Thorough". "Resume analysis" on a cancelled deepening re-posts its own scope and target, never a whole-project run.
- **S9 resume keeps the job's cost limit.** A cancelled run starts again with the limit it had, which may have been raised during the run. Keep paused hides the notice for that pause only: reaching a new limit shows it again.
- **S25 day numbers** come from the server: the inventory's `days[].n` uses `retrieval.capture_dates` and `trip_day`, as deepening does. A day in the list is always the day that gets deepened.
  - Day 1 is `retrieval.first_capture_date`, streamed rather than loaded (invariant 13).
  - A clip counts on the day it starts, while deepening places each segment by its own start, so a clip that runs past midnight can add work to the next day as well.
- **S25 days.** The day list comes from the inventory's days, which now carry clip counts, plus the places from the trip context. "Current selection" uses the segment ids the Library passes when it opens the dialog. Until the Library exists (step 7) it explains how to select. A run with nothing new to add (`job_id: null`) says so and starts nothing.

## Consequences

- S21 (step 9) edits the same settings with the same sources.
- When location-aware prompts arrive, they must read `ai.send_gps` through the project settings, and make it part of their artifact keys (invariant 9). Until then, S8's GPS hint must not suggest the toggle does anything beyond keeping location local.
- The progress view reads the control DB's task table once per poll; S9 polls at most every 2 s.
