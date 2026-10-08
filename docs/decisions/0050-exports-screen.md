# 0050 — The Exports screen (S20)

- Status: accepted (M2 step 8d)
- Deciders: agent (autonomous; no human gate)

## Context

S20 is the render queue and history. The mockup has five columns plus actions: cover, edit and version with the preset label, status with progress, size, time, and actions. It shows a project header and the line "Renders are saved in …".

The rail's Exports item, however, is global (`/exports`), and render ids are numbered per project (ADR 0047). The mockup's actions:
- Cancel (rendering);
- Remove (queued);
- Open and Show in Finder, or Copy link (done);
- Details and Re-render (failed).

## Decision

- **Route.** S20 is `/p/:pid/exports`. Inside a project, the rail's Exports opens it. Outside one, `/exports` opens the most recently opened trip's exports, or says "Open a trip to see its exports." when there is none. S17's Exports button opens the edit's project's page.
- **Rows** come from `GET /projects/{pid}/renders`: newest first, 50 per page, with "Show more". The screen polls every 2 s while any row is queued, rendering or paused.
  - **Cover:** a frame of the version's first shot, in its own shape.
  - **Edit:** the edit's name and a version chip.
  - **Preset:**
    - "Preview · 720p", "Web · 1080p" or "Web · 4K" in the edit's native shape;
    - "Web · 1080p vertical" or "Web · 1080p square" for 9:16 and 1:1;
    - "Web · 4K · 4:5" or "Web · 4K · 2.39:1" for the other shapes.
    - A frame capped at 4096 px is named by its long side.
  - **Status:**
    - Queued
    - Rendering n %, with a bar
    - Paused
    - Done
    - Failed
    - Cancelled
    - File deleted
    - File missing
  - **Size** is the file's size on disk.
  - **Time** is how long the render took ("9 m 12 s"). A failed render shows "Stopped at n %", taken from its job's progress.
- **Actions:**
  - Queued: **Remove**. Rendering or paused: **Cancel**. Both cancel the render; chunks that are already made stay cached.
  - Done:
    - **Open** plays the file in a new tab;
    - **Download** saves it;
    - **Delete** removes the file after a confirmation ("The edit stays, and you can render it again at any time"). The row stays as history.
  - Failed: **Details** opens a dialog with the job's error, offering Close and Re-render. **Re-render** sits next to it.
  - Cancelled, deleted or missing: **Re-render**.
  - "Show in Finder" waits for the desktop app (ADR 0047). On the web, Open and Download stand in for it and for "Copy link".
- **Where it differs from the mockup:**
  - The actions column is 220 px rather than 180 px, to fit the third button (Delete).
  - Sizes follow the app's `formatBytes`, so the mockup's "17.6 GB" reads "18 GB" (one decimal only under 10).
  - A lossless master reads "Master · 1080p": the M2 master is FFV1, not ProRes (S19 is M4).
  - Every row action's accessible name includes the edit and version ("Open Costa Rica — 5 min cinematic v3").
- **The folder line** shows the project's renders folder (`MosAic/renders`), as the server sees it.

## Consequences

- A final rendered from S17 shows in S20 within one poll, and so does a preview started there.
- S20 now shows every render in the project. Filtering by edit is left for a later milestone; S17 already lists one edit's renders.
