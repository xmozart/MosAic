# ADR 0013 — L2: mosaic layout, vision without a key, dispositions that keep user decisions

- **Status:** accepted (agent decision, M0 step 9c)
- **Date:** 2026-10-04

## Context

`ARCHITECTURE.md §8` stages 10, 11 and 13 define labelled mosaics, one vision observation
per segment, and USE/MAYBE/REJECT dispositions from rules plus AI. `ANALYSIS_MODES.md`
gives 16 tiles per mosaic for Balanced. The spec leaves these questions open:

- How tiles are chosen and laid out, and how large a sheet should be.
- What happens to analysis when the vision provider cannot be used (no key, or
  `ai.local_only` on). M0 acceptance 7 requires a clear "not configured" message, never a
  crash.
- `disposition` rows reference segments, but segments are rebuilt with new ids whenever
  their inputs change. Invariant 10 makes user decisions hard constraints until the user
  resets them.
- Rule thresholds.

## Decision

1. **Layout.**
   - Sheets are per asset, with segments in time order. Each segment gets up to 4 tiles
     spread over its kept samples: the usable range first, then the whole segment, then the
     nearest kept sample of the same shot.
   - A segment is never split across sheets. Unused rows are cropped.
   - The sheet width is the vision provider's effective image size (`AdapterLimits.max_image_px`;
     1568 px for Claude) on a 4 × 4 grid. Tiles are capped at the 640 px sample thumbnails.
   - Limits are static per provider and model, so planning a sheet needs no key.
   - The label `T07 · ast_0123 · 00:02:14.3` (logical asset time) uses Pillow's embedded
     Aileron font (CC0), never a runtime fetch.
   - `mosaic_tile` rows and a JSON sidecar map each tile to its sample, segment and source
     ticks.
2. **Vision v1.**
   - One call per sheet through `AIClient`. Segments are cited as `S1…` and tiles as `T01…`.
   - Every field is an ordinal or an enumeration: shot type, camera motion, people,
     interest, composition, and issues.
   - `best_tile` is resolved by code to a sample and its ticks.
   - A new `AIClient` `validate` hook enforces what a schema cannot: every segment is
     answered exactly once, and each `best_tile` belongs to its own segment. A failure is
     retried once with the errors, then the task fails (invariant 6).
   - The prompt forbids naming places, landmarks, brands or people (invariant 16).
3. **No usable vision provider ⇒ the vision task is skipped**, with the "not configured"
   reason naming the `mosaic config` command.
   - Analysis still completes, and dispositions fall back to rules only.
   - Once a provider is configured, re-running analysis fills in the observations.
   - Cached answers are reused, so a repeat run makes zero calls.
4. **User decisions survive re-segmentation.**
   - Every disposition row stores its asset and the source range it was made on
     (`anchor_*`).
   - When segments are purged, AI rows are deleted. User rows are detached
     (`segment_id` NULL), never deleted.
   - After new segments are written, each detached user row is re-attached to the segment
     it overlaps most. The newest decision wins a segment; the others stay detached, and so
     are kept.
   - The analysis stage writes only `source = "ai"` rows. `effective()` prefers the user
     row.
5. **Rules.**
   - REJECT: an asset shorter than 2 s, a usable range under 0.7 s, black frames (median
     near-black ≥ 0.9), obstruction (median ≥ 0.6), or frozen for ≥ 80 % of the segment.
   - MAYBE: dark, partly frozen, very shaky (top 5 % *and* 3 × the wobble floor), or blurry
     (bottom 5 % *and* a raw variance of the Laplacian under 15).
   - AI issues: `accidental`, `pocket_or_covered` and `obstructed` mean REJECT;
     `usable: false` means REJECT; the other issues, or low interest with poor
     composition, mean MAYBE.
   - The most severe status wins, and every reason is kept.
   - The thresholds are first estimates, calibrated on the real corpus in step 12.
6. **Stage registration** no longer depends on import order. A stage module imports the
   modules of the stages it runs after, and `plan_stages` checks `after` for project
   stages too.

## Consequences

- An owner without a key can still analyze and edit from L0/L1 data.
- The extra synthetic cases `accidental` and `pocket` exercise the REJECT rules.
- A sheet with a single short segment wastes the rest of its tiles. Its token cost is small
  because unused rows are cropped.
- A user decision whose range later overlaps no segment stays stored but detached. Review
  UIs (M2+) should list such orphaned decisions.
- The stage-level vision provenance row marks the stage complete and lists the per-call
  provenance. Costs are recorded only on the per-call rows, so nothing is counted twice.
- When vision cannot run (no key, `ai.local_only` on), the stage is skipped before any
  cache lookup. Answers cached earlier stay stored and are used again when a provider is
  usable. Serving them while the provider is off is not worth a second code path in M0.
- Mosaic and vision keys include upstream provenance ids, and `is_done` also checks the
  rows. A segments purge followed by identical segments (SQLite reuses row ids) therefore
  rebuilds the sheets, and the AI answers come from the cache.
