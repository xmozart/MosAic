# 0051 — Project storage, removal and diagnostics

- Status: accepted (M2 step 9a)
- Deciders: agent (autonomous; no human gate)

## Context

**S21's mockup** shows how much MosAic stores for a project in four groups (Previews, Frames & contact sheets, Renders, Analysis), each tagged Regenerable or Kept. It offers "Clear regenerable files", and a Danger zone that removes MosAic's data from the folder. Its acceptance criterion: clearing never deletes durable data.

**S23** lists tasks with their tool, time, tokens and cost, opens one task's detail with Retry and Skip, and exports a redacted bundle. M2 acceptance 3: no secret ever appears in it.

Three constraints shaped the design:
- **A cleared artifact must come back when needed.**
  - The proxy stage checks its files, so a cleared preview is made again by the next analysis.
  - The frame pass is part of the visual stage, whose done-check is its own result artifact, not every frame. A cleared frame would never come back, and library tiles would go blank.
- **Invariant 8:** long work runs as jobs. A job, however, belongs to a registered project, and removal unregisters the project.
- **A worker may still hold a removed project open.** On close it writes a checkpoint snapshot into `<folder>/MosAic`, which would bring the folder back.

## Decision

- **Storage groups** (`GET /projects/{pid}/storage`). Sizes come from the artifact index in one query; renders and the database are measured on disk.
  - **Regenerable:**
    - Previews (`proxy`, `tickmap`);
    - Render cache (`chunk`).
    - Their stages check the files.
  - **Kept:**
    - Frames & contact sheets (`frame`, `mosaic`), unlike the mockup's "Regenerable" tag. Their stages check database rows, not files, so a cleared frame or sheet would never come back: library tiles would go blank and a vision re-run would fail.
    - Renders (the owner's outputs).
    - Analysis (the database and every other artifact).
  - **After a clear, previews come back with the next analysis.** Until then, the library and S17 players and preview renders wait for them. S21's confirmation says so.
- **Clear regenerable files** (`POST …/storage/clear-cache`) is a job with one IO task (`storage.clear`). It deletes the regenerable artifacts' files and their index rows, 500 at a time. The next analysis or render makes the files again.
  - **It never runs alongside other work:**
    - it is refused (409) while any job of the project runs;
    - while it runs, the executor refuses new jobs for the project (409, "clearing this project's regenerable files");
    - the task itself stops between batches if another job appears. A test checks that every table other than the artifact index keeps its row count, and that the originals' bytes are unchanged.
- **Removal** (`DELETE /projects/{pid}/workspace {confirm_name}`) needs the project's exact name, and is refused while a job runs. The handler only does fast work:
  - It releases the lease and closes the project.
  - It takes the project's open lock exclusively, as relocation does. While any other handle holds the project (a window, the server or a worker), removal is refused (409). Workers now close projects that have no unfinished job, so an idle worker never blocks it.
  - It renames the folders MosAic owns to `.MosAic.mosaic-removed-<date>-<id>`:
    - These are `<root>/MosAic` and `<app data>/projects/<ULID>`. The id must be a ULID and match the request, because it comes from a file in the user's folder. Links are refused, and so is anything else, never the folder itself.
    - The rename stays in the same parent, so it is instant.
    - The targets are written to the trash list before the renames. If a rename fails, the folders already renamed go back, the list entries are dropped, the lease is taken again, and the request returns 409 "nothing was removed".
  - It deletes the descriptor and unregisters the project and its edit index.
  - A background purge then deletes the renamed folders. It also runs at start-up, so an interrupted purge finishes.
  - **This is an exception to invariant 8.** The purge is a bounded `rmtree` of folders that are no longer part of any project, so no job could own it. A purge only ever deletes names that removal created.
- **Checkpoint guard.** A split project whose outputs folder no longer exists skips its snapshot. A worker that still holds the project therefore never recreates `MosAic/`.
- **Diagnostics:**
  - **Task list:** `GET /diagnostics/tasks?project=&status=&cursor=` returns the newest first. A row's tool is the AI provider and model, with summed tokens and cost from the usage records, or else the tool that runs that task kind (ffprobe, ffmpeg, whisper, siglip…).
  - **Task detail:** `GET /diagnostics/tasks/{tid}` adds the error, params, result, events, worker, start time and the actions allowed.
  - **Actions:**
    - `POST /diagnostics/tasks/{tid}/retry` resets a failed task, or one cancelled by a failure, plus the tasks it cancelled ("dependency failed"). It is refused for a job the owner cancelled, and for a project that was removed.
    - `…/skip` accepts a failed task as skipped. The tasks it cancelled run, as they would after any skipped dependency, and the job finishes. It is refused for a job the owner cancelled.
  - **The mockup's "Command" line is not shown.** Tasks do not record their FFmpeg command lines, and adding that is out of M2's scope. The detail shows the error output instead.
- **The bundle** (`POST /diagnostics/bundle`, a zip):
  - **Contents:** a manifest, system info, settings and providers, the last 200 jobs and 2,000 tasks with their errors, and the last 1 MB of each log.
  - **Excluded:** no project database, media or keys.
  - **Redaction is applied twice:**
    - **By value:** every secret MosAic can load is replaced wherever it appears. That covers each provider's key, every `MOSAIC_SECRET_*` variable, the master key (variable or file), and MosAic's Docker secret files.
    - **By pattern:** strings shaped like keys are masked: `sk-…`, bearer tokens, `api_key=…`, and the `user:password` part of a URL.
    - **By key name:** mapping keys named as secrets (`api_key`, `master_key`, `token`…) lose their values. Whole names only, so token counts (`tokens_in`, `max_tokens`) stay.
    - List rows are redacted too.
    - **Log tails** start at a whole line, so a cut never leaves part of a key. The newest logs come first, up to 5 MB in all.
  - A test plants a deployment key in a task's error and params and in a log, and scans every file in the bundle for it.

## Consequences

- The API returns five groups: previews, render cache, frames & contact sheets, renders and analysis.
- **Windows (M3):** the exclusive lock file lives inside the folder being renamed, and on Windows an open handle blocks renaming a directory. The desktop build must release the lock just before the rename, or keep it outside the folder.

- S21 can show what clearing frees and what it keeps. A cleared preview comes back with the next analysis.
- Making frames regenerable, by checking frames in the visual stage's done-check, is left for a later milestone.
- Deleted projects leave no MosAic folder behind, even after a crash during the purge.
