# 0058 — Local model downloads, and app-level jobs

- Status: accepted (M3 step 2)
- Deciders: agent (autonomous; no human gate)

## Context

M3 and S1 ask for first-run downloads of the speech and image-understanding models:
- with checksums;
- with a progress UI;
- resuming after a restart (S1 acceptance: "a model download interrupted by quitting resumes on next launch").

Until now the adapters downloaded weights on first use through the Hugging Face cache, inside an analysis task, with no progress and no verification of the content.

Invariant 8 requires long work to run as a job. Every job so far belonged to a project, and the worker opened that project for each task. A model download belongs to the app.

## Decision

- **Catalog** (`ai/local_models.py`). Each model a provider profile can use is a set of files pinned to:
  - a repository revision (the same revision as the adapter's pin; a test keeps them equal);
  - a byte size;
  - a SHA-256. LFS files use the hub's own SHA-256; small files were hashed once.

  The entries:

  | Entry | Files | Size |
  |---|---|---|
  | `whisper-small` | | 0.49 GB |
  | `whisper-medium` | the default speech model | 1.53 GB |
  | `whisper-large-v3` | Thorough | 3.09 GB |
  | `siglip-base` | the default image model: vision, text and tokenizer | 0.82 GB |
  | `siglip-quantized` | | 0.21 GB |

  The licenses are MIT (Whisper and the Systran CTranslate2 conversions) and Apache-2.0 (SigLIP), both already in `LICENSES.md`.
- **Download.** Each file streams from `huggingface.co/<repo>/resolve/<revision>/<file>` into `<file>.part` under `models/local/<entry>/`.
  - A partial file continues with an HTTP Range request. A server that ignores the range restarts that file.
  - A file is renamed into place only when its size and SHA-256 match. On a mismatch the `.part` is deleted, so a retry starts that file over.
  - An entry is installed when every file is in place at its size.
  - Bytes are written as they arrive, so a dropped connection loses nothing.
  - A 206 must start where the `.part` ends (`Content-Range`). Otherwise the `.part` is dropped and the retry starts the file over.
  - **One download per model at a time.** Two attempts on one model would append to the same `.part`: a double request, or a lease taken over while the old attempt still runs. The task takes a non-blocking OS file lock on the model folder (`filelock`, MIT, macOS and Windows) and defers while another attempt holds it. The OS releases the lock with the process, so a crash leaves none.
  - The task is skipped when the model is already installed (`is_done`, invariant 9). A cancelled download keeps its `.part` for the next one.
- **Adapters.** Whisper loads the folder, and SigLIP its files, when the matching entry (same revision) is installed. Otherwise they keep the M0 behaviour, the Hugging Face cache on first use. Developer machines and CI keep their shared caches.
- **App-level jobs.**
  - `jobs.model.APP_PROJECT = "_app"` owns jobs that belong to no trip.
  - A handler registered with `@task(..., app_level=True)` runs without opening a project. Its `ctx.project` is a `NoProject` that raises on use.
  - The job queue, leases, retries, cancel, SSE progress and the worker supervisor (ADR 0056) apply unchanged. S23's Retry accepts them, since they have no project to have been removed.
  - The activity popover names these jobs "MosAic".
- **Progress in units.** A task may report its own progress (`ctx.report(done, total)`; bytes here) at most twice a second. It goes into `job.result.progress`, and `JobProgress.pct` uses it while the job runs (capped at 99 until the task finishes).
- **Resume after quitting.** The job stays queued in the control DB. On the next launch the supervisor starts a worker, the task is leased again, and the download continues from the `.part` files. A failed attempt (offline) is retried by the queue. S1's Retry calls the job's `retry-failed` after the queue gives up.
- **API.**
  - `GET /api/models/local` lists each entry with: label, capability, size, downloaded bytes, installed, `needed` (the current provider profile uses it) and its active download job.
  - `POST /api/models/local/{name}/download` returns the running job, a new job, or `job_id: null` when the entry is installed.

## Consequences

- S1 and Settings can show real sizes and progress, and the first analysis on a fresh Mac doesn't stall on a hidden download when S1 ran first.
- Weights downloaded through the old path stay in the Hugging Face cache and are not counted as installed. Downloading through S1 fetches them once more.
- App-level jobs are available for other app-wide work later (the benchmark is still per project).
