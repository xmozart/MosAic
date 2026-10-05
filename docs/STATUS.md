# STATUS

The agent maintains this file. It is the resume point for every new session.

## ⚠ Waiting for owner

_(empty — the agent is working)_

## Current

- **Milestone:** M0
- **Step:** 10 (editing); step 9 done (9a config, 9b AI layer, 9c mosaics/vision/dispositions, 9d Claude Code / Codex CLI providers at the owner's request, ADR 0014). The owner approved the M0 plan; ADR 0002 records the decisions. ADR 0003: AI provider, key and corpus path are app settings the owner enters later via `mosaic config`; don't gate on them before step 12 needs them.
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
- [ ] 10. Editing: retrieval, planner, selector, solver, refiner, critic, versions, `mosaic edit`/`report`
- [ ] 11. Render: chunks, conform, tone mapping, pillarbox, silence, loudnorm, encoder selection
- [ ] 12. Acceptance in `make ci`, `make eval` on the corpus, draft expectations, reports, findings → gate G6

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
