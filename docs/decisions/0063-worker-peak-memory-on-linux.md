# 0063 — The scale test measured pytest's memory on Linux, not the worker's

- Status: accepted (M3 step 6, after the M3.6 push). Supersedes the "Workers on Linux" part of ADR 0062.
- Deciders: agent (autonomous; no human gate)

## Context

ADR 0062 put the 40-hour scale test's Linux memory failure (about 1.7 GB against 1.5 GiB) down to glibc malloc arenas and capped them with `MALLOC_ARENA_MAX=2`. The next GitHub run reported 2.46 GB, more than before.

The failure is in the measurement, not the worker:

- **Linux keeps the parent's peak in the child's `ru_maxrss`.** The test starts the worker with `subprocess.run` from the pytest process. The child is a fork of pytest, and at `exec` Linux records the old memory's high-water mark in the child's `ru_maxrss`. A child that uses 8 MB reports 1513 MB when its parent holds 1.5 GB (checked in `python:3.12-slim`). `VmHWM` in `/proc/self/status` belongs to the new image only. macOS does not do this.
- **The number grew with the test suite.** In `make ci` the scale test runs late, after acceptance tests that load ONNX Runtime and CTranslate2 into pytest. Its "worker peak" rose with each milestone: 1.72 GB in the first GitHub run with the test (M1.14, run 37414311306; other failures joined later), about 1.8 GB through M3.5, and 2.46 GB at M3.6, which added the M3 acceptance tests.
- **The worker's own peak is about 0.5 GB everywhere.** A diagnostic branch ran the scale test alone on three GitHub `ubuntu-24.04` runners (run 38105435498), sampling `/proc/self/smaps_rollup` every 5 s. The results: 490 MB as-is, 479 MB with transparent huge pages disabled, and 493 MB with the arena cap lifted. Linux containers on arm64 and x86-64 gave 476 to 480 MB, and macOS gives 473 MB. The arenas made no difference.

The same runs measured the S14 estimate at 1.74 s, 2.30 s and 1.98 s against its 2 s budget, and a library list page at 248 to 302 ms against 300 ms. GitHub's runners vary between AMD EPYC 9V74, EPYC 7763 and Xeon 8573C.

## Options

1. Keep `ru_maxrss` and raise the budget. Rejected: the budget is right, and the number is wrong.
2. Run the worker through `posix_spawn` or a clean launcher. This is fragile: Python picks vfork or fork itself, and both carry the parent's mark.
3. Read the worker's own high-water mark, `VmHWM`, on Linux, and keep `ru_maxrss` on macOS.

## Decision

- Option 3. The scale test's worker reports `VmHWM` on Linux. The 1.5 GiB budget is unchanged.
- **The arena cap is removed:** `worker_env`, the Docker image's `MALLOC_ARENA_MAX`, and their unit tests. It fixed nothing, and its stated reason was wrong.
- `segment_facts` no longer scans every range metric that starts before a segment. It starts at the segment's start minus the longest range. It skips the sample-time query when only range metrics were asked for, and it takes the segments the caller already loaded (retrieval). Its results are unchanged: they are compared against the previous version on the 40-hour project, and `test_segment_facts` still passes.

## Consequences

- The memory assertion now measures the worker, so it can catch a real regression.
- The estimate's 2 s and the list page's 300 ms budgets have little margin on GitHub's slower runners. The `segment_facts` change helps a little. If those budgets still fail on GitHub, the next step is to make retrieval cheaper per asset, for example by storing each segment's shake percentile when segments are built. The budgets stay where they are.
