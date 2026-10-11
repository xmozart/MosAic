# 0065 — A settled heap and retrieval that reads only what it ranks

- Status: accepted (M3 step 6, after the M3.6d push)
- Deciders: agent (autonomous; no human gate)

## Context

GitHub run 38147073782 (M3.6d) failed two timing budgets on the runner:

- **5,000-clip library filters (300 ms).** One filter change took 362 ms while the other twelve took about 100 ms. In the previous run a different filter stalled the same way (351 ms).
  - The stall is a full garbage-collector pass. The test runs the analysis in its own process, so about 270,000 objects stay alive. Each gen-2 pass scans all of them: about 47 ms here, and roughly five times that on the runner.
  - The real server holds less, since jobs run in worker processes. But everything imported and built at startup is still scanned on every pass.
- **40-hour edit estimate (2.0 s).** It took 2.04 s on the runner and about 600–700 ms here. It is real work: `retrieve` ran about six queries per clip (2,400 in total), loaded about 23,000 ORM objects, and read every per-second shake range of every segment (144,000 rows). It did this although ranking and capping never read shake or transcripts.

## Decision

1. **Settled heap.** `mosaic serve` builds its app, then calls `settle_heap()`: `gc.collect()` then `gc.freeze()`.
   - What the server holds once its app is built is moved out of the collector's scans.
   - Garbage is collected first, so nothing collectable is frozen.
   - Objects freed by reference counting are still freed. Only cycles that form among frozen objects later are never collected, and objects built at startup do not do that.
   - It runs once per process, so `create_app` does not call it: tests build many apps.
   - The timing tests measure requests on the heap as served: `tests/support/heap.as_served` settles it and unfreezes it afterwards.
2. **Retrieval in batches.** Clips are read 64 at a time (`CLIP_BATCH`; invariant 13 still bounds memory).
   - Each batch runs a few queries: segments and in-force dispositions as plain rows (`_Seg`, `InForce`), clip decisions, observations and reviews.
   - `decisions.resolve` now takes any objects with the fields it reads (`SegmentFields`, `DispositionFields`), so the single decision rule is unchanged.
3. **Shake and transcripts for the final candidates only.** After the cap (at most 200, plus the owner's forced picks), `_describe` fills them in.
   - Shake comes from `dispositions.shake_percentiles`: one query per clip, using a new index `ix_tech_metric_asset_name_start (asset_id, name, start_ticks)`, added by project migration `b7c3e9d1a246`.
   - The new index starts with `asset_id`, so the single-column `asset_id` index it covers is dropped.
   - It shares `metric_window` and `shake_metric_name` with `segment_facts`. The new test checks the two agree on random data, including gyro clips that also carry optical shake.
   - `tests/unit/test_retrieval_batches.py` checks the batched `retrieve` against clip-at-a-time reading, across batch edges and the cap. Its fixture has owner decisions, clip rules, observations with reviews, speech and gyro shake.
4. **Budgets unchanged.**

## Consequences

- **Measured here.**
  - The 40-hour estimate takes 130–145 ms (it was about 700 ms). Candidates and counts are identical to before on the 40-hour project, checked against the previous `retrieve`.
  - The 5,000-clip filters all take 40–56 ms. A full GC pass during requests takes about 10 ms (it was about 47 ms).
- **Index cost.** Writes cost about the same: one index replaces another. Opening an older project builds the new index once (about 0.6 s on the 40-hour project).
- **One concern holds the rule.** Retrieval candidates carry shake and transcripts only after capping. A new ranking signal that needs them must move into the batch read.
