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

## Consequences

- S21 (step 9) edits the same settings with the same sources.
- When location-aware prompts arrive, they must read `ai.send_gps` through the project settings, and make it part of their artifact keys (invariant 9). Until then, S8's GPS hint must not suggest the toggle does anything beyond keeping location local.
- The progress view reads the control DB's task table once per poll; S9 polls at most every 2 s.
