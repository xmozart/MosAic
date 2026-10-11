# 0062 — GitHub CI is the reference; Linux worker memory

- Status: accepted (M3 step 6)
- Deciders: agent (autonomous; no human gate)

## Context

Every step since M2.8d committed after a local `make ci` on the owner's Mac, while the GitHub `ci` workflow on `ubuntu-24.04` was red. Nobody looked at it until the M3 report's review. It failed for three different reasons:

1. **A lockfile mismatch.** `npm ci` failed on Linux (M2.9c and M2.9d). The `@emnapi` pins fixed it in M2.10.
2. **A race in S7.** `TripContextScreen` once saved the trip details from before a parse merge. The mutation's function is refreshed after render, and a Save right after the merge used the previous one. It shows only on a loaded runner, but a user could lose a paste the same way.
3. **Memory on Linux.** The 40-hour scale test's worker peaked at 1.73 GB against its 1.5 GiB budget on the 4-core runner, against about 0.5 GB on macOS. glibc gives each thread its own malloc arena, up to 8 per core, and a worker runs many slot threads. A Docker server would carry the same overhead.

The new `desktop` workflow also failed: Tauri's build script requires the bundle's resource folders, which `make desktop-check` ran before.

## Decision

- **GitHub CI is the reference.** A step is done when its commit's GitHub runs are green, not only the local `make ci`. After each push, the agent checks `gh run list` and fixes a red run before going on. The milestone reports cite run IDs.
- **S7** sends the save body with the click (`save.mutate(forSave(value))`): exactly what is on screen.
- **Workers on Linux** start with `MALLOC_ARENA_MAX=2` unless it is set (`jobs.client.worker_env`, used by the server's supervisor and the CLI). The Docker image sets it too. The scale test starts its worker with the same environment, so it measures what production runs. Its budget is unchanged.
- **`make desktop-check`** creates empty resource folders first.
- **The S14 estimate's margin.** The full local `make ci` for this step measured the 40-hour estimate at 2.04 s against its 2 s budget (1.4 s when M2.11a set it), so it sat too close to the line.
  - Retrieval reads only the shake metric of each segment, but `segment_facts` loaded every metric, about 600,000 rows per estimate. It now takes the metric names it needs (`only=SHAKE_METRICS`), with the same shake values (a test compares them).
  - The estimate dropped to 0.77 s. The budget is unchanged.

## Consequences

- Two arenas can cost a little throughput in allocation-heavy threads. The analysis is bound by FFmpeg and the models, not by malloc.
- Until the next green GitHub run, this fix for the Linux memory peak is reasoned, not proven. The M3 report records that run.
