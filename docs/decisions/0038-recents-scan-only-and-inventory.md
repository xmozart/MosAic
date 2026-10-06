# 0038 — Recents from the control DB, scan-only jobs, and inventory

- Status: accepted (M2 step 5a)
- Deciders: agent (autonomous; no human gate)

## Context

The S3, S4 and S5 screens set these rules:
- **S3 Home:** "Cards render from the control DB without opening project DBs. Missing folders are detected without blocking the list."
- **S4:** `/projects/preview` makes no writes. `POST /projects` returns "project, plus a scan job".
- **S5 Inventory:** shows what the scan found before analysis. Unsupported reasons come from the camera-profile catalog, never from raw ffprobe.
- **S6 Clock check:** sits between S5 and S8 in the reference journey.

Until now, the only scan job was the first task of a full analysis.

## Decision

- **Cards.** `project_registry.card` (JSON, added by a control migration) holds each project's card:
  - clips, photos and whole footage seconds;
  - first and last date;
  - 3 cover sample ids: frames of USE clips, best quality first, or the first kept frames before analysis;
  - whether the analysis has run, and the latest edit's name.

  The worker refreshes the card at every project checkpoint, and `POST /projects` sets it at creation. `GET /projects` reads the registry and the job table only:
  - **Status chip:** a running scan or analysis job gives `scanning` or `analyzing` with its percentage. Otherwise the status is `analyzed` (with its mode), `scanned` or `not_analyzed`.
  - **Missing folders:** every folder is checked in parallel within 0.5 s. A folder still unanswered (an offline share) reports `missing: null` rather than delaying the list.
- **Existing projects.** A folder that already is a project is recognised by its descriptor, or for external placement (which writes nothing in the folder) by the control DB's registry.
  - Preview then returns its id.
  - `POST /projects` opens it as it is (`created: false`) and ignores a requested placement; changing placement belongs to S21.
  - A placement the folder can't take (for example `in_folder` on a network or read-only folder) answers 422 and writes nothing.
- **Missing-folder checks** run on daemon threads, so a hung stat on an offline share delays neither the response nor app shutdown.
- **Folders.** The desktop sends an absolute path; a server sends `{root, path}` through the media-root gate (ADR 0035). `folder` in responses follows the same rule, so a server never returns a server path.
- **Preview.** `POST /projects/preview` writes nothing. It returns:
  - the storage class and suggested placement (`PLACEMENT_FOR_CLASS`);
  - quick video and photo counts by extension, capped at 50,000 entries, with `complete` when the walk finished;
  - the existing project's id if the folder is already a project.
- **Create.** `POST /projects` creates the project, or opens it with `created: false` when the folder already is one. It holds the lease and starts a scan-only job.
  - A scan-only job has kind `scan` and `params.scan_only`. It runs scan → probe → group, and grouping does not spawn the analysis stages.
  - S8 starts the analysis, which reuses the probes.
- **Inventory.** `GET /projects/{pid}/inventory` returns:
  - `summary`: footage, clips, photos, dates, cameras;
  - `cameras`: grouped by device, else by profile, with kind, counts, files, footage, badges (HDR, Log, Live Photo, 360, Telemetry) and the clock suggestion when one exists;
  - `days`: footage seconds per camera per day;
  - `attention`:
    - unreadable files, grouped by catalog reason and fix;
    - 360 clips (analysis only);
    - cloud-only files, with their size;
  - `notes`: chaptered recordings, Live Photos and bursts.
- **Cloud download.** `POST /projects/{pid}/cloud-files/download` starts a job that reads each cloud-only file through. Reading makes the OS download it, and nothing is written to the original. The job then rescans in scan-only mode.
- **Clock suggestions need analysis.** They are built from frame evidence across devices (ADR 0027), which exists only after L1. So before the first analysis, S5 shows no clock warning and S6 has nothing to suggest; both appear once a pass has run. S6 can also be opened from Library, as in the reference's "Review clocks" link.

## Consequences

- Cards for projects opened before this change appear at their next checkpoint. Until then they show zero counts and the name.
- The status chip's percentage is the job's task completion, the same value as S9.
