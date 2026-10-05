# STATUS

The agent maintains this file. It is the resume point for every new session.

## ⚠ Waiting for owner

_(empty — the agent is working on M1)_

## Current

- **Milestone:** M1
- **Step:** M1 step 5 (hierarchical summaries); steps 1–4 done (trip context, L3 deep review, Airshow re-eval: aircraft 45 → 79 %, crowd 29 → 2 % by primary subject, 0 must-exclude violations; analysis modes).
- **Dev setup for a fresh session:** `uv sync`; LGPL FFmpeg 8.1.2 lives in `.tools/ffmpeg/bin` (rebuild with `make ffmpeg` if missing); `make ci` must pass.

## M0 plan

- [x] 1. Scaffold, `core/time.py` with property tests, FFmpeg builders and license/capability probe, LGPL FFmpeg build script, synthetic corpus generator with barcodes
- [x] 2. Storage: control and project DBs, placement classifier, descriptor, artifact store, provenance, `mosaic init`, float-seconds schema test
- [x] 3. Jobs: DAG, leases, Executor, worker process, resume after kill; FastAPI skeleton with `/api/jobs` and SSE
- [x] 4. L0: probe, camera profiles, chapters, sidecars, unsupported reasons, deferred photos
- [x] 5. Proxies: tone mapping, rotation, color range, VFR→CFR, tick map
- [x] 6. Shots, samples, tech metrics, shake
- [x] 7. Audio: VAD, Whisper word ticks, loudness, speech fixture
- [x] 8. Embeddings, segments with usable_range, similarity groups, GPMF if feasible
- [x] 9. Mosaics, AI interface and provider registry, Anthropic and fake adapters, app configuration and `mosaic config` CLI (ADR 0003), vision v1, budgets, dispositions
- [x] 10. Editing: retrieval, planner, selector, solver, refiner, critic, versions, `mosaic edit`/`report`
- [x] 11. Render: chunks, conform, tone mapping, pillarbox, silence, loudnorm, encoder selection
- [ ] 12. Acceptance in `make ci`, `make eval` on the corpus, draft expectations, reports, findings → gate G6

## M1 plan

Order: the owner's G6 priority first (Airshow: aircraft and the F-35 demo over crowds), then the rest of the milestone.

- [x] 1. Trip context: `trip_context` table; `mosaic context` CLI (import JSON or free text, AI-parsed and shown for confirmation); context in planner/selector v2 and in summaries; names allowed only from context (invariant 16)
- [x] 2. Thorough L3 review: full-resolution single frames of candidate segments (sky/aircraft, MAYBE "not usable", top candidates), context-aware, with the `reviewer` capability (Sonnet 5.5); deepening scoped to project, day or selection; cost ceiling with pause → raise → resume (acceptance 5, 7)
- [x] 3. Airshow re-eval with context + Thorough → compare against M0 (aircraft share, crowd share, F-35 coverage)
- [x] 4. Analysis modes Quick/Balanced/Thorough/Custom (ANALYSIS_MODES.md): per-mode detectors, tile density, LRF proxies in Quick, estimates
- [ ] 5. Hierarchical summaries shot → day → trip (context changes re-run summaries only)
- [ ] 6. Storage placement split/external (macOS and Linux detection), artifact store relocation, DB snapshots via the backup API, cloud placeholders, read-only folders (acceptance 1, 2)
- [ ] 7. Project lifecycle: reopen, relink by fingerprint, new/missing/changed files, lease locks with read-only open (acceptance 3)
- [ ] 8. Camera profiles insta360, nikon, dji and the unsupported-reason catalog (acceptance 4)
- [ ] 9. Photos: HEIC/JPEG/NEF/DNG ingest, Live Photo pairing, bursts, photo+video moments, photos in mosaics and vision (licence-clean decoders)
- [ ] 10. Clock correction (per-device offsets, CLI) and colour: per-profile hints, user LUTs for log sources
- [ ] 11. Hybrid search: SigLIP text→image + FTS5, RRF; API and CLI
- [ ] 12. Hardware probe and benchmark → estimates; worker pool resource classes and per-provider rate limits
- [ ] 13. Scale: the 40-hour synthetic project, bounded memory, list API < 300 ms (acceptance 6)
- [ ] 14. M1 acceptance suite, `make eval`, `docs/reports/M1.md`; then continue to M2

## Carry-forward notes

- Pass `allow_gpl_ffmpeg` into media_tools instead of reading storage from media/; consider integer micro-USD for usage costs.
- A job paused at its cost limit needs a way to raise that job's `cost_limit_usd` before resuming (S9/S20, API `resume` parameter).
- Step 12: wire the per-`make eval` run ($5) and per-milestone ($25) budgets (AGENT_WORKFLOW §4) as job cost limits and a running total.

- Similarity groups are rebuilt (new ids) whenever their key changes; once dispositions or user decisions refer to groups, reference segments or give groups stable identity (invariant 10).

- Step 12: calibrate `library.similarity.MAX_DISTANCE` (0.06) and `segments.VISUAL_CHANGE` on the real corpus; synthetic frames are degenerate for SigLIP (25% of pairs ≥ 0.94).
- `media.telemetry` re-runs (and ends skipped) on every analysis for assets without GPMF; cheap, but could cache a 'no telemetry' artifact.

- Artifact GC: old `frame`/`motion`/proxy artifacts stay when keys change (M1 storage cleanup).
- Dev note: tests share Whisper/SigLIP weights in MosAic's real app-data `models/` folder (`MOSAIC_MODELS_DIR`), so they download once.

- Dev gotcha: an auto-started worker lives ~20 s after its last job and keeps running the code it loaded; wait or kill it after code changes.
- M1 follow-ups from analysis modes (M1.4): LRF first-frame PTS alignment check in `lrf_matches` (a one-frame offset passes today); SQL aggregates in `library/estimate.py` and a scoped photo count for deepen estimates; move `_project` to `app/deps.py`; hypothesis test for `plan_samples`/`threshold_cuts`.
- M1 follow-ups from step 4: GoPro timelapse flag; Apple Log / GoPro flat `log(<name>)` color hints; Live Photo pairing by the still's own content identifier; relink-by-fingerprint probe keys.
- GoPro `creation_time` is camera-local time labelled UTC; per-device clock offsets come with M1 (S6 clock check).

- Structured JSON logs with job_id/task_id/project_id (ARCHITECTURE §16): worker uses plain logging for now; add before M1 diagnostics work.

- Step 12: calibrate the disposition thresholds (`library.dispositions`, ADR 0013) on the real corpus, and look at real Haiku observations on Airshow/Dubai sheets before trusting the AI issue mapping.
- `dispositions._facts` scans all of an asset's metrics per segment (O(segments × metrics)); sort and bisect before multi-hour assets (M1 scale work).
- Orphaned (detached) user dispositions need a place in review UIs (M2+); they are kept, never deleted (ADR 0013).
- Step 10/12: run `core.timecheck.find_float_times` over real DB JSON rows and the edit JSON export (acceptance 4, JSON half).

## Log

_(one line per commit: date · step · summary)_

- 2026-10-04 · M0.1 · scaffold, exact time types, LGPL FFmpeg 8.1.2 build + probe, typed builders, barcoded synthetic corpus, CI, LICENSES (ADR 0004)
- 2026-10-04 · M0.2 · control/project DBs with Alembic trees, placement classifier (M0 refuses non-local), descriptor, artifact store with required provenance, `mosaic init`, migrated-schema float and drift tests (ADR 0005)
- 2026-10-04 · M0.3 · job DAG store (atomic leases, heartbeats, expiry requeue, cancel cascade), Executor, worker process with resource-class slots, kill -9 resume test, FastAPI `/api/jobs` + SSE `/api/events`
- 2026-10-04 · M0.4 · L0 inventory: scan, probe (artifact blobs, integer streams), iPhone/GoPro/generic profiles, GoPro chapters with logical-time map, LRF validation, unsupported reasons, deferred photos, reconciliation; `mosaic analyze`, `mosaic-dev inspect` (ADR 0006)
- 2026-10-04 · M0.5 · 720p CFR SDR proxies (tone mapping, rotation, range, VFR→CFR, chapters concatenated) with verified affine or PTS-table tick maps; frame-accurate barcode tests (ADR 0007)
- 2026-10-04 · M0.6 · shots (ported adaptive detector), samples with pHash dedupe and thumbnails, tech metrics with set-based percentiles, optical-flow shake; project write gate; OpenCV dropped for GPL FFmpeg bundling (ADR 0008)
- 2026-10-04 · M0.7 · audio: streaming BS.1770 loudness, Silero VAD, faster-whisper word ticks from proxy audio, LibriSpeech fixture; PyAV excluded (ADR 0009); bundled runtime libs documented (ADR 0010, Q-1); LRF flake fixed
- 2026-10-04 · M0.8 · SigLIP (ONNX) sample/segment embeddings in per-kind sqlite-vec indexes, segments with usable_range, leader-clustered similarity groups, GPMF gyro shake; asset-scoped keys and purge-before-rebuild fixes (ADR 0011)
- 2026-10-04 · M0.9a · app configuration: settings/provider profiles/secret refs/usage tables, keyring secrets, `mosaic config` CLI, /api/settings, /api/providers, /api/secrets (ADR 0003)
- 2026-10-04 · M0.9b · AI provider layer: capability protocols, registry, Anthropic + fake/replay adapters, AIClient (cache, atomic budget reservation, validate+retry, usage/provenance), ai test/reset-key, validate endpoint; Whisper/SigLIP behind adapters (ADR 0012)
- 2026-10-04 · M0.9c · Labelled mosaics sized to the vision provider, vision v1 (one call per sheet, code-checked segment/tile references), USE/MAYBE/REJECT dispositions from rules + AI with user rows kept across re-segmentation; vision skipped with the fix when not configured; accidental/pocket corpus cases; import-order-safe stage registration (ADR 0013)
- 2026-10-04 · M0.9d · Owner request: `claude-cli` and `codex-cli` providers drive the installed Claude Code / Codex apps with the owner's sign-in (no API key) for all AI capabilities; `mosaic config ai use <provider>` presets; app-presence readiness check; real `ai test` and a real vision pass verified on the dev Mac (ADR 0014)
- 2026-10-05 · M0.10 · Editing: request/pace/timeline rate, capped retrieval with similar-clip fallback, planner v1 + selector v1 (validated refs), deterministic solver, cut refiner (words, sentences, settle, frame grid), jump-cut fixer + backfill, critic metrics, immutable versions with JSON export, `mosaic edit`/`report`, edit API (ADR 0015)
- 2026-10-05 · M0.11 · Render: per-event chunks (copyts trims across chapters, nearest-frame conform, tone mapping, pillarbox, gain/fades, silence fill, exact frame and sample counts), stream-copy assembly with two-pass loudnorm, preview/final/lossless profiles, chunk reuse, `mosaic render`, render API, barcode frame-accuracy checker (ADR 0016)
- 2026-10-05 · M0.12a · Acceptance suite (every synthetic case analyze → edit → lossless render, barcode-exact; no float times; zero repeat AI calls), `make eval` runner (G1/G2 gates, budgets via job cost limits and a ledger, drafted expectations, results, rubric), paused-job handling in the CLI (ADR 0017). Stopped at G1.
- 2026-10-05 · M0.12c · `make eval` on the owner's corpus via Claude Code: Airshow 3:00 (49 shots) and Dubai 1:15 (16 shots), exact durations, every blocking metric 0, −14.2/−13.9 LUFS, $0 API spend. Fixed: FFmpeg select-term limit, AAC sample check, AI 'not usable' → MAYBE, CLI served-model provenance. Report M0.md and ADR 0001 written → G6.

- 2026-10-05 · G6 · Owner reviewed M0: results not bad; Airshow needs aircraft/F-35 focus, fewer crowds; context is key. Recorded in results and ADR 0001 (accepted). M1 starts.
- 2026-10-05 · M1.1 · Trip context (model, CLI, API, parse job), planner/selector v2 with context, eval context.json + subject metric
- 2026-10-05 · M1.2 · L3 deep review (full-res frames from originals, reviewer capability, deep_review supersedes L2), mosaic deepen, raise-and-resume cost limits (ADR 0018); later capabilities inherit the single chosen provider (ADR 0019)
- 2026-10-05 · M1.3 · Airshow re-eval: AI 'obstructed' rejects only unusable clips (accidental/pocket always), primary-subject metric; aircraft 79 %, crowd 2 %, 0 must-exclude violations; Q-2 on the confirmed must-include list
- 2026-10-05 · M1.4 · Analysis modes Quick/Balanced/Thorough/Custom: per-job ModeConfig, LRF camera proxies (frame-accurate) and 540p in Quick, threshold detector, mode tiles and Whisper model, L2/L3 stage levels, scoped deepening that adds L2 then L3 (acceptance 5), estimates API, `analysis-runs` API, `mosaic analyze --mode/--set/--estimate` (ADR 0020)
