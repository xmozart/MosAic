# 0043 — Clip detail: moments, reasons, quality and position

- Status: accepted (M2 step 7a2)
- Deciders: agent (autonomous; no human gate)

## Context

S11 shows one clip:
- its position in the day ("Day 3 · 2 of 44") with previous and next clips;
- a player with the usable range and moment markers;
- a transcript you can click;
- the AI-vs-you line;
- **Why**, **Moments**, **Quality** (Sharpness, Steadiness, Exposure, Audio as Good, Fair and so on), **Used in edits** and **Note**;
- for photos, a burst strip.

The mockup labels transcript lines with speaker names ("Leo:", "Anna:") and writes "Why" as prose. The API only listed field names.

## Decision

- **Moments** are the clip's segments in time order. Each has:
  - exact `{ticks, tb}` bounds and its usable range;
  - the decision in force, with who made it (`user`, `clip` or `ai`, from `decisions.for_segments`) and the AI's own status beside it;
  - the vision description and interest;
  - the AI's reasons in plain words;
  - a frame.

  The player marks the moments, and S11 lists the ones that have a description.
- **Why** is the AI's description of the clip's best moment (USE over MAYBE, then high interest), plus that moment's reasons in plain words (`REASON_WORDS`). Unknown codes are spelled out from the code. Nothing is generated for display. The text is what the analysis wrote, which follows invariant 16.
- **Quality** compares the clip with the rest of the trip. These are heuristics for M2: they are good enough to read at a glance, not measurements.
  - **Sharpness:** the median sharpness percentile. Photos and videos share the percentile pool.
  - **Steadiness:** 1 minus the shake percentile. The gyro metric (`shake_gyro`) is used when the clip has telemetry, as the dispositions do (`library.quality.shake_metric_name`).
  - **Exposure:** distance of the mean level (0–255, scaled to 0–1) from mid-grey (0.45), less clipping.
  - **Audio:** integrated loudness from −50 to −20 LUFS. Wind is subtracted only when the clip has no speech, because voices carry low-frequency energy too.

  Each becomes a word: below 0.25 Poor, below 0.5 Fair, below 0.85 Good, otherwise Excellent. A score that wasn't measured is null.
- **Transcript.** Sentences with timed words, paged 200 sentences at a time, in the clip's time base, so a click seeks exactly. **No speaker names.** Nothing identifies speakers, and invariant 16 forbids naming people who don't come from the trip context, metadata or the user. Speaker identification stays out of scope (CLAUDE.md: no named people).
- **Position** follows the library's order and its default filter (rejected clips hidden unless `show_rejected`). Day numbers are the library's.
- **Used in edits** lists the edits whose latest version cuts the clip: an exact `json_each` match on the events' `asset_id`, never a text search through the JSON.
- **Similar** lists up to 12 other clips that share a similarity group, each shown by its first kept frame. **Burst** applies to photos: the members of its burst group, with the best one marked.
- **The photo line** shows the camera and the capture time. S11b also shows aperture, shutter speed and ISO, but no stage records those EXIF fields yet. Adding them to the photo stage is a later step, and the API will gain an `exif` object then.
- **The tile status and the AI-vs-you line** (`status_shown`, `decided_by`, `ai_status`) come from the clip's per-segment decisions (`for_segments`). This is the same rule as the library's SQL (ADR 0042), so the detail never disagrees with the grid.
- **Position.** Unsupported files are not in the grid, so their `position` is null. A rejected clip is placed among rejected clips even when the grid hides them. The clip's name is its first path in sort order, as the grid names it.
- **Reasons on a USE moment are caveats**, such as "Shaky". The client labels them as such.
- **Transcript paging** is keyed by sentence id. The audio stage writes sentences in time order, so id order is time order.

## Consequences

- If speaker identification is ever added, it needs its own ADR and must respect invariant 16.
- Quality words depend on trip-wide percentiles, so they can shift a little after re-analysis.
