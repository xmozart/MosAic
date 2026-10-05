# ADR 0022 — Split and external placement, snapshots and relocation

- **Status:** accepted (agent decision, M1 step 6)
- **Date:** 2026-10-05

## Context

ARCHITECTURE.md §4 defines three placements: `in_folder`, `split` and `external`. M0
supported only `in_folder` (ADR 0002 A). M1 acceptance 1 and 2 require split for network
and cloud-synced folders, external for read-only folders, snapshots at checkpoints, and
proof that no SQLite file on such a folder is ever opened read-write. The spec left these
details open: where the local workspace lives, how an external project is found again,
what a checkpoint is, how a snapshot avoids opening SQLite on the folder, and what a
placement override does to an existing project.

## Decision

- **Two locations per project** (`storage/projects.py`):
  - *live*: the project DB and the artifact cache;
  - *outputs*: edit JSON exports, renders and DB snapshots. `Project.workspace` now means
    *outputs*.

  | placement | live | outputs | descriptor |
  |---|---|---|---|
  | in_folder | `<root>/MosAic` | `<root>/MosAic` | folder |
  | split | app data `projects/<id>` | `<root>/MosAic` | folder |
  | external | app data `projects/<id>` | app data `projects/<id>/outputs` | app data |

  Proxies and cache are therefore never written to a network or cloud folder.
- **Snapshots.**
  - The SQLite online backup API writes into a unique local scratch file next to the live
    DB. The file is then copied into the folder through a unique part file and an atomic
    rename. SQLite never opens a file on the folder, and concurrent writers never share a
    temporary file.
  - All SQLite opens go through `sqlite_engine` (`make_engine`, `backup`), which calls
    `OPEN_HOOKS`. The acceptance test records every path and asserts that none is inside
    the folder.
  - A sidecar `project.db.json` records the project id and a **generation** that
    increases with each published snapshot.
  - Snapshots of one live DB are serialized by a lock file (`flock`) across threads and
    processes.
- **Checkpoints are explicit.**
  - Task handlers opt in (`@task(..., checkpoint=True)`): group, normalize, similarity,
    dispositions, summaries, edit generation (the edit commit) and render assembly.
    Per-file and per-clip tasks never snapshot, and the acceptance test asserts at most
    one snapshot per checkpointing stage.
  - `close()` checkpoints too, but nothing is published when the DB has not changed.
    File stats are the cheap test. When they differ (a write, or SQLite merging its WAL
    on close), the digest of a local backup decides. Request-scoped handles (API
    requests) close without a checkpoint.
  - A failed snapshot is logged and never changes a task's outcome or fails a close.
- **Seeding and computers taking turns.**
  - A split folder opened without a live DB is seeded from its snapshot (a plain copy),
    but only if the sidecar names this project.
  - If the folder's snapshot is newer (higher generation) than this computer's last
    snapshot:
    - when the live DB is unchanged since its own last snapshot, it is moved aside and
      replaced;
    - when it has changes too, the open is refused with an explanation
      (`SnapshotConflictError`), rather than either side losing work.
  - Only a sole opener may replace a live DB: opens try the open lock exclusively first.
    When another handle (such as a running worker) has the project open, a newer
    snapshot is picked up later, never under it.
  - A checkpoint never overwrites a newer snapshot. Relocating away from split first
    takes the folder's newer snapshot, or stops on a conflict.
  - The artifact cache is not in the snapshot. Artifacts are checked on disk, so missing
    proxies and analysis are recomputed when needed.
- **External projects.**
  - Nothing is written to the folder. The descriptor lives in app data, and the project
    registry stores the folder's path and a **folder fingerprint**: relative paths and
    sizes of the first 256 files in sorted walk order. No file contents are read. A
    folder with no such files has no fingerprint.
  - Opening looks up the path first (newest registration). The fingerprint is computed
    and used only when that misses. It matches only a project whose registered folder no
    longer exists, and only a single one: a moved card is found again, while two copies
    that both exist are two projects.
- **Overrides and relocation** (`init_project(placement=…)`, `mosaic init --placement`):
  - In-folder on a network or cloud-synced folder is refused (invariant 2). A read-only
    folder accepts only external.
  - Every open project holds a shared lock on `.open.lock` in its live directory.
    Relocation needs that lock exclusively and is refused while the project is open
    anywhere.
  - Relocation is copy-then-switch. The DB is copied with the backup API, which includes
    its WAL; if the old folder became read-only, it is read with a read-only connection.
    The cache and outputs are merged into the new location, and then the descriptor is
    written. Only after that are the old copies deleted, and failures there are logged
    and left. A crash at any point leaves the old copy as the project.
  - Original footage is never touched.
- **Unchanged from M0:**
  - Offline cloud files are listed as offline and never read (scan and probe already did
    this).
  - Windows cloud-file attributes are still a TODO for the Windows desktop build (M3).

## Consequences

- Network and cloud folders work without risking DB corruption, and the folder stays
  portable through its snapshot.
- Read-only cards and archives work fully, with outputs in app data. `mosaic init` prints
  both locations.
- App data grows with split and external projects' caches. Cache cleanup is a storage
  follow-up (artifact GC).
