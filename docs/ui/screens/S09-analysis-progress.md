# S9 — Analysis Progress

- **Reference:** `docs/ui/reference/` → S9-AnalysisProgress, S9b-ProgressStates
- **Milestone:** M2

**Purpose.** A calm, informative view of a long-running analysis.

## Layout

**Ready-to-browse banner** at the top (after the `analysis.ready_to_browse` event) with Open library / Create edit.

**Left column:**

- overall card: big %, time left (only once reliable), cost so far against the limit, progress bar, clips done, Pause/Cancel
- `StageList`
**Right column:**

- live card: the current contact sheet with tile labels T01…, the latest AI description in italics, file and day
- failure banner

## States

- Running.
- Paused by user.
- Paused at cost limit.
- Completed.
- Completed with failures (Retry failed).
- Cancelled (work kept, Resume).

## Data & API

- `/jobs/{id}`, SSE `job.*`, `/jobs/{id}/pause|resume|cancel|retry-failed`.

## Acceptance

- ETA hidden until 10% of tasks are complete.
- The live card updates at most every 2 s.
