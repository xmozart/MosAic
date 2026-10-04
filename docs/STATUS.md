# STATUS

The agent maintains this file. It is the resume point for every new session.

## ⚠ Waiting for owner

_(empty — the agent is working)_

## Current

- **Milestone:** M0
- **Step:** 6 (shots, samples, tech metrics, shake). The owner approved the M0 plan; ADR 0002 records the decisions. ADR 0003: AI provider, key and corpus path are app settings the owner enters later via `mosaic config`; don't gate on them before step 12 needs them.
- **Dev setup for a fresh session:** `uv sync`; LGPL FFmpeg 8.1.2 lives in `.tools/ffmpeg/bin` (rebuild with `make ffmpeg` if missing); `make ci` must pass.

## M0 plan

- [x] 1. Scaffold, `core/time.py` with property tests, FFmpeg builders and license/capability probe, LGPL FFmpeg build script, synthetic corpus generator with barcodes
- [x] 2. Storage: control and project DBs, placement classifier, descriptor, artifact store, provenance, `mosaic init`, float-seconds schema test
- [x] 3. Jobs: DAG, leases, Executor, worker process, resume after kill; FastAPI skeleton with `/api/jobs` and SSE
- [x] 4. L0: probe, camera profiles, chapters, sidecars, unsupported reasons, deferred photos
- [x] 5. Proxies: tone mapping, rotation, color range, VFR→CFR, tick map
- [ ] 6. Shots, samples, tech metrics, shake
- [ ] 7. Audio: VAD, Whisper word ticks, loudness, speech fixture
- [ ] 8. Embeddings, segments with usable_range, similarity groups, GPMF if feasible
- [ ] 9. Mosaics, AI interface and provider registry, Anthropic and fake adapters, app configuration and `mosaic config` CLI (ADR 0003), vision v1, budgets, dispositions
- [ ] 10. Editing: retrieval, planner, selector, solver, refiner, critic, versions, `mosaic edit`/`report`
- [ ] 11. Render: chunks, conform, tone mapping, pillarbox, silence, loudnorm, encoder selection
- [ ] 12. Acceptance in `make ci`, `make eval` on the corpus, draft expectations, reports, findings → gate G6

## Carry-forward notes

- Step 9: replace the `MOSAIC_ALLOW_GPL_FFMPEG` env override in `media/tools.py` with the `allow_gpl_ffmpeg` dev setting in `user_preferences`.
- Dev gotcha: an auto-started worker lives ~20 s after its last job and keeps running the code it loaded; wait or kill it after code changes.
- M1 follow-ups from step 4: GoPro timelapse flag; Apple Log / GoPro flat `log(<name>)` color hints; Live Photo pairing by the still's own content identifier; relink-by-fingerprint probe keys.
- GoPro `creation_time` is camera-local time labelled UTC; per-device clock offsets come with M1 (S6 clock check).

- Structured JSON logs with job_id/task_id/project_id (ARCHITECTURE §16): worker uses plain logging for now; add before M1 diagnostics work.

- Step 10/12: run `core.timecheck.find_float_times` over real DB JSON rows and the edit JSON export (acceptance 4, JSON half).

## Log

_(one line per commit: date · step · summary)_

- 2026-10-04 · M0.1 · scaffold, exact time types, LGPL FFmpeg 8.1.2 build + probe, typed builders, barcoded synthetic corpus, CI, LICENSES (ADR 0004)
- 2026-10-04 · M0.2 · control/project DBs with Alembic trees, placement classifier (M0 refuses non-local), descriptor, artifact store with required provenance, `mosaic init`, migrated-schema float and drift tests (ADR 0005)
- 2026-10-04 · M0.3 · job DAG store (atomic leases, heartbeats, expiry requeue, cancel cascade), Executor, worker process with resource-class slots, kill -9 resume test, FastAPI `/api/jobs` + SSE `/api/events`
- 2026-10-04 · M0.4 · L0 inventory: scan, probe (artifact blobs, integer streams), iPhone/GoPro/generic profiles, GoPro chapters with logical-time map, LRF validation, unsupported reasons, deferred photos, reconciliation; `mosaic analyze`, `mosaic-dev inspect` (ADR 0006)
- 2026-10-04 · M0.5 · 720p CFR SDR proxies (tone mapping, rotation, range, VFR→CFR, chapters concatenated) with verified affine or PTS-table tick maps; frame-accurate barcode tests (ADR 0007)
