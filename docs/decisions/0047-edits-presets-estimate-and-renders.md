# 0047 — Edit cards, story presets, the edit estimate and render management

- Status: accepted (M2 step 8a)
- Deciders: agent (autonomous; no human gate)

## Context

S13 (Edits), S14 (wizard steps 1, 2 and 6), S17 (player and report) and S20 (Exports) need data the M0 endpoints did not have:
- edit status and cover;
- story preset cards with collages built from the owner's own clips;
- a time and cost estimate before creating an edit;
- render progress, size and time;
- cancel, re-render, delete and a playable render file.

The API map leaves several of these open:
- **Render ids.** `/renders/{rid}/…` is written without a project, but render ids are numbered per project database.
- **Edit statuses.** S13 lists "Generating n %", "Preliminary", "Preview ready" and "Final rendered", but nothing records whether an edit was made during analysis.
- **The estimate.** S14 shows "About 3 min · ~$0.40", but there is no model of an edit's cost.
- **Story cards.** S14b shows eight story cards, Custom among them, while PRODUCT.md lists sixteen presets.

## Decision

- **Edit cards** (`GET /projects/{pid}/edits`, cursor-paged by edit id; `editing/cards.py`).
  - Each card carries the cover frame (the first shot's first kept sample), versions, duration in frames, aspect, resolution and status.
  - Status is the first of these that applies:
    1. `generating` (with its percent);
    2. `failed` (the newest edit job failed after the newest version);
    3. `new`;
    4. `final` (a final render is done);
    5. `preview` (a preview render is done);
    6. `rendering`;
    7. `ready`.
  - `preliminary` is a separate flag. The edit job records `metrics.preliminary` when an analysis job of the project was active at its start or its end. Regenerating after analysis makes a new, non-preliminary version whenever the analysis changed the candidates. If the candidates did not change, the key is equal, the existing version is kept, and so is its flag.
- **Story presets** (`GET /projects/{pid}/presets`). All sixteen PRODUCT.md presets are listed, seven of them `featured` in S14b's order.
  - The eighth card, **Custom**, is a frontend card that offers the other nine presets plus the instructions box. There is no "custom" story value.
  - **Collages** (`GET /projects/{pid}/presets/{id}/collage` → `{frames: [sample_id…]}`):
    - The preset's query runs through library search in visual mode: image embeddings, plus the text index over descriptions and tags.
    - Rejected moments are skipped, and only one frame per clip is used.
    - The diary, and any shortfall, is filled with the best moments spread over the trip.
    - The endpoint only reads, and the frames are served by `/media/{pid}/frame/{id}`.
- **The edit estimate** (`POST /edits/estimate {project_id, request}`; `editing/estimate.py`).
  - Retrieval runs exactly as generation would, with no AI call. That gives:
    - the candidate count;
    - the usable footage length (`enough_footage`);
    - the edit key.
  - If a version with that key already exists, the plan is reused: the cost is $0 and the time is seconds.
  - Otherwise, the planner input is the prompt plus the candidate lines, and the selector input adds the plan. Output tokens are a range of the calls' limits (as in the analysis estimate), priced by the configured models.
  - Time is 20–120 s per call. This is a display default until M4 measures it.
  - A running analysis returns `preliminary: true` and `analysis_pct` for S14's banner.
- **Renders.**
  - Render actions live under the project, because render ids are per project:
    - `POST /projects/{pid}/renders/{rid}/cancel` and `/rerender`;
    - `DELETE /projects/{pid}/renders/{rid}/file`;
    - `GET /projects/{pid}/renders/{rid}/file` (Range requests; `?download=true` makes it an attachment).
  - **One rule for a render's state** (`render.service.render_state`): a pending row whose job ended without a result (it failed, or was cancelled from Activity) takes the job's end. The rows, the edit cards, Cancel (409 unless queued or running) and Re-render (409 while queued or running) all use it.
  - **Rows** carry a label (`Preview · 720p`, `Web · 4K · 9:16`, `Master · …`), a status (queued, rendering n %, paused, done, failed, cancelled, deleted, missing), size, time and error, plus the renders folder.
  - **Cancel** marks the render cancelled and cancels its job. An assembler that finishes after a cancel deletes its output instead of marking the render done. Chunks stay cached, so a re-render reuses them.
  - **Delete** removes the rendered file, which is a derived output and never an original. The row stays as history.
  - **Reveal ("Show in Finder")** waits for the desktop app, which has no shell yet in M2. On the web, S20 offers Open and Download.
- **The report's rejected list** follows ADR 0042.
  - It is `decisions.rejected_segments()`, the SQL form of `resolve`. A property test checks it against `resolve`.
  - It includes clips the owner rejected whole (`whole_clip`, source `user`, "You rejected the whole clip") and their unanalysed segments.
  - Each entry carries plain-language `words` and its source file.

## Consequences

- A vertical copy or a duplicate request is estimated at $0 because it reuses the plan.
- The renders list no longer returns an absolute server path per row. The folder is returned once, and files are reached through the file endpoint.
- The `/renders/{rid}/*` rows in API_MAP are updated to the project-scoped paths.
