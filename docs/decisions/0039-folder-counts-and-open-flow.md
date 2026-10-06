# 0039 — Folder counts, the open flow before Tauri, and removing from recents

- Status: accepted (M2 step 5c)
- Deciders: agent (autonomous; no human gate)

## Context

- **S4b** shows a count line under each folder ("412 videos · 1,180 photos"). The confirm dialog says "Found N videos and M photos in K folders".
- A trip folder usually keeps its footage in sub-folders (DCIM, per-camera, per-day), so counting only the top level would show 0 for most trips.
- An unbounded walk of a large NAS share could hold the listing for minutes.
- S4 asks the confirm dialog to make no writes and to be instant. Durations and cameras need ffprobe, which is a scan.
- The desktop folder picker is a native Tauri dialog, and Tauri comes in a later step.
- S3's card menu offers "Remove from list". The spec does not say what is removed.
- Reconnect (S3 missing state) in server mode can't take a host path, because the server browser deals only in root + relative path (ADR 0035).

## Options

1. **Counts:** top-level only (fast, wrong for nested trips); a full recursive walk (right, unbounded); a recursive walk with a cap and a time budget (right for normal trips, bounded).
2. **Preview content:** probe a sample for duration and cameras, or show counts and folders only.
3. **Desktop picker before Tauri:** wait for Tauri, or a path field.
4. **Remove from list:** delete the project data, or drop only the recents entry.

## Decision

- **Counts are recursive and bounded.** `quick_counts` walks with `os.scandir`. It skips hidden entries and MosAic's own folder, does not follow symlinks, and stops after 20,000 entries per folder or at a deadline (`complete: false`, shown with "+").
  - The browse listing has one 2-second budget: the current folder is counted first, then its sub-folders. A walk that reaches the deadline stops inside the loop, and its count is a lower bound. Folders not reached in time return `counts: null` and show no count line.
- **Preview shows counts and folders only.** Nothing is probed before the user creates the project. Duration, cameras and dates appear on S5 once the scan-only job has run.
- **"Open existing project"** uses the same picker as "Open footage folder". Preview recognises a folder that is already a project, by its descriptor or, for external placement, by the registry, and opens it without the confirm dialog.
- **"Reveal in Finder"** (S3 hover menu, desktop) waits for Tauri, which can open the system file manager. The browser UI can't.
- **Desktop uses a path field** (`PathDialog`) until the Tauri native picker lands. It goes through the same preview and create API.
- **Remove from list** (`DELETE /projects/{pid}/recent`) hides the project from recents. It sets `project_registry.hidden_at` (a control migration) and releases the lease the way `close` does.
  - The row is kept: it is an external project's only link to its workspace, and indexed edits reference it.
  - Footage, the descriptor and the workspace stay.
  - Opening the folder again clears the flag and brings the project back with its analysis, for every placement.
  - Deleting MosAic data stays on S21 (`DELETE /workspace`).
- **Server relink takes `{root, path}`** and is confined by `media_roots.within`: 403 outside a root, 404 for a refused path, 422 for a folder that isn't this project's, or when `choose_folder` is sent as well.

## Consequences

- A folder with more than 20,000 entries shows a lower bound. That is acceptable for a browse hint; the scan is exact.
- The confirm dialog can't warn about long or mixed footage before creation. S5 covers that.
- When Tauri lands, the path field is replaced by the native dialog. The API does not change.
