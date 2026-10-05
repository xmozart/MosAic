# ADR 0023 — Project lifecycle: relinking and leases

- **Status:** accepted (agent decision, M1 step 7)
- **Date:** 2026-10-05

## Context

M1 acceptance 3 requires that a trip folder moved to another disk relinks every file with
no re-analysis. ARCHITECTURE.md §14 defines project locks: a lease file `MosAic/.lock`
(holder, host, pid, expiry) "plus a control-DB record", with read-only open, takeover
after expiry, and force-unlock after a warning. S0 shows "open elsewhere", "files moved"
and "lost lease" states, and API_MAP lists `open`, `close` and `relink`.

In M0, a changed mtime reset a file to pending, which re-probed it and dropped its probe
key. A file renamed inside the folder became a new record, and the old one was marked
missing.

## Decision

- **Relinking in the scan.**
  - Known path, same size, but a different mtime (a folder copied with a tool that drops
    times): the content fingerprint (size plus first and last 64 KiB) is recomputed. If
    it matches, only the mtime is updated. The status, probe key and everything keyed on
    them stay, so nothing is probed or analyzed again.
  - New path: after the walk, a new path whose size and fingerprint match a record that
    is no longer at its path is that file, moved or renamed. Its record (id, fingerprint)
    follows it. The probe key includes the path, because camera profiles read file names,
    so a moved file is probed again. Its content-keyed proxy and analysis are reused.
  - A file that is back after being missing, with the same fingerprint, is probed again
    and reuses its keyed analysis.
  - **Assets follow their files.** Asset keys are built from paths. When a group's key
    is new but all its files already belonged to one asset (not claimed by another key
    in this run), that asset is re-keyed instead of a new one being created. Its id
    survives, and with it its analysis, ratings, USE/REJECT, locks and edit references
    (invariant 10).
  - Fingerprints (file reads) are computed in a first pass outside the project's single
    writer. The write session only applies the results.
  - The scan result reports `relinked`.
  - Limits:
    - The fingerprint is size plus the first and last 64 KiB, so an in-place edit to the
      middle of a file that keeps its size is not detected.
    - Identical duplicates are matched to records arbitrarily, which is harmless for
      content.
- **Relinking the project folder** (`POST /projects/{pid}/relink {choose_folder?}`).
  - Without a body, the project's folder is re-scanned. If that folder is gone, the
    response is 409 so the UI asks where it went.
  - With `choose_folder`, the folder is accepted if its descriptor names this project, or
    if it is an external project and its folder fingerprint matches. Then the project's
    root moves there and it is re-scanned.
  - The re-scan uses the mode of the project's last analysis, so a Quick project is not
    recomputed at Balanced density.
  - Files are always below the project root. A "choose folder" for individual clips
    elsewhere is not supported.
- **Leases** (`storage/lease.py`).
  - `.lock` lives in the project's outputs folder: `<root>/MosAic` for in-folder and split
    projects, app data for external ones. It holds the holder (the installation id),
    host, pid, acquisition time and an expiry 5 minutes ahead.
  - Processes of one installation (app, CLI, worker) share the lease. Leases only guard
    against other computers.
  - An open for editing (`open_project`, `init_project`) acquires or renews the lease, and
    raises `LeaseHeldError` (API 409 with holder info) when another installation holds a
    live lease.
  - An expired lease is taken over silently. A live one only with `take_over` (API) or
    `mosaic lock --take-over` (which asks first).
  - A **read-only open** never takes the lease. It refuses DB writes
    (`ReadOnlyProjectError`, 409), artifact writes and snapshots.
  - CLI read commands (`report`, `summary`, `context show`, `analyze --estimate`) open
    read-only.
  - **API routes declare what they do.** Writing and job-submitting routes (analysis
    runs, relink, context save and parse, edits, generation, renders) need edit access.
    They are refused (409) when the app opened the project read-only or lost its lease;
    otherwise they take or renew the lease. Read routes open read-only unless the app
    holds the lease, so a read never takes it and works while another computer edits.
  - After writing, the file is read back, so when two computers race the last writer
    wins and the other gets the error.
- **Renewal.**
  - The worker renews before each task, and also from the task heartbeat during long
    tasks. A renewal younger than a third of the TTL is skipped, so network folders are
    not written per task. If another computer took the project over, the worker drops
    the project, a starting task fails with the holder's name, and a running task is
    cancelled.
  - The API server renews the projects it opened (`POST /open`) in a background thread.
    A lease lost to a takeover turns the project read-only on the server and is reported
    as `lock.lost` until the user accepts read-only.
  - The renewal thread survives any error. A lost read-back race counts as lost.
    Renewal never forces, so a takeover is never undone.
  - `POST /close` and server shutdown release the lease.
  - An unreadable lease file (a flaky share) is an error, never "free".
  - The CLI does not release on exit; its lease lapses after 5 minutes. Releasing
    immediately could open a gap while the app (same installation) still has the project
    open. `mosaic lock --release` releases explicitly.
- **No control-DB lease record.** The lease file is the single source of truth, because
  it is the only state the other computer can see. The registry's `last_opened_at`
  already gives "recent" for S3.

- **Clock skew.** Expiry is the writer's wall-clock time. Computers whose clocks differ
  by more than about 3 minutes (the TTL minus the renewal interval) can misjudge a live
  lease as expired. Desktop clocks are network-synchronized, so this is accepted and not
  compensated.

## Consequences

- Moving or copying a trip between disks keeps all analysis, and the acceptance test
  asserts that no analysis task (probe included) runs and no AI call is made.
- Two computers never edit one project at the same time without an explicit takeover.
  Together with snapshot generations (ADR 0022), this covers both concurrent and
  alternating use.
- Follow-ups:
  - locks on Windows (desktop, M3);
  - a shorter lease wait for API requests;
  - a relink **preview** for S0's "n clips aren't where they used to be; found m in
    <path>" (UI, M2).
