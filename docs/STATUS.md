# STATUS

The agent maintains this file. It is the resume point for every new session.

## ⚠ Waiting for owner

_(empty — the agent is working on M2)_

## Current

- **Milestone:** M2 (M1 complete: `docs/reports/M1.md`)
- **Step:** M2 step 3b (media roots, folder browser, path safety); steps 1–3a done; M1 complete (trip context, L3 deep review, Airshow re-eval: aircraft 45 → 79 %, crowd 29 → 2 % by primary subject, 0 must-exclude violations; analysis modes; summaries; split/external placement; relink and leases; camera profiles; photos; clock and LUTs; search; hardware benchmark and rate limits; 40-hour scale test).
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

## M2 plan

Order: design foundation first (milestone rule), then the server pieces the browser needs, then screens along the main journey, then Docker and the acceptance suite. Stop at G6 with `docs/reports/M2.md`.

- [x] 1. Frontend foundation: Vite + React + TS strict, Tailwind with tokens generated from `tokens.json`, shadcn mapping, bundled Geist fonts, dark/light themes (OS default, user override), Vitest, Storybook, OpenAPI-generated client, FastAPI serving the built app, `make ci` runs frontend lint/typecheck/tests
- [x] 2a. Design-system components: primitives (Button, TextField, Segmented, Switch, Kbd), media (DispositionChip, DispositionControl, StarRating, IncludeToggle, CameraBadge, QualityRow, ClipTile with every listed state), system rows (StageList, ModeCard, EstimateCard, PlacementBadge, UnsupportedRow, ClockOffsetRow, SettingRow, SecretField, StorageBreakdown), stories per state, AI-vs-you test (acceptance 8)
- [ ] 2b. Data-bound components come with the screen step that first uses them, each with its stories: shell (AppRail, ActivityPopover, ProjectHeader, CommandPalette, Toast, ConfirmDialog) in 5; Player, Filmstrip, Waveform, Transcript in 4/7; library (VirtualGrid, LibraryToolbar, GroupHeader, DayScrubber, BulkBar, ClipInspector, SimilarShots) in 7; editing basics in 8
- [x] 3a. Server mode sign-in: single admin (Argon2), HttpOnly SameSite=Strict Secure session cookie, double-submit CSRF on writes, lockout after 5 failures, security headers with a hashed-inline-script CSP, `MOSAIC_MODE`/`MOSAIC_BIND`/`MOSAIC_ALLOWED_HOSTS`, S2 screen and auth gate
- [ ] 3b. Media roots (`/admin/media-roots`), `/fs/browse` and every path-taking endpoint confined to media roots in server mode, path-safety API tests (acceptance 2)
- [ ] 3c. Server secret backends: env, Docker secrets, encrypted file with a master key; write-only entry, last-4, validate
- [ ] 4. Media endpoints: proxy with HTTP range, frames, filmstrip, waveform; `Player`
- [ ] 5. Shell and journey I: S0 app shell + dialogs + command palette, S3 Home, S4 Open folder, S5 Inventory, S6 Clock check, S7 Trip context
- [ ] 6. Journey II: S8 Analysis setup (mode cards, estimates), S9 progress over SSE (pause/resume/cancel/retry), S25 Deepen
- [ ] 7. Library: S10 (virtual grid, filters < 300 ms, hover-scrub, bulk, keyboard), S11 clip detail, decisions API, S12 search (acceptance 4, 5)
- [ ] 8. Edits basic: S13, S14 basic, S17 player + report, S20 exports queue
- [ ] 9. Settings: S21 project, S22 app (five config scopes with source and Reset, providers, keys), S23 diagnostics
- [ ] 10. Docker: multi-arch image with LGPL FFmpeg, compose (plain, NVIDIA optional), healthcheck, volume layout doc
- [ ] 11. Acceptance: compose end-to-end to a rendered preview (1), secret scan (3), visual regression both themes (6, 7), OpenAPI coverage (9), `docs/reports/M2.md` → G6

## M1 plan

Order: the owner's G6 priority first (Airshow: aircraft and the F-35 demo over crowds), then the rest of the milestone.

- [x] 1. Trip context: `trip_context` table; `mosaic context` CLI (import JSON or free text, AI-parsed and shown for confirmation); context in planner/selector v2 and in summaries; names allowed only from context (invariant 16)
- [x] 2. Thorough L3 review: full-resolution single frames of candidate segments (sky/aircraft, MAYBE "not usable", top candidates), context-aware, with the `reviewer` capability (Sonnet 5.5); deepening scoped to project, day or selection; cost ceiling with pause → raise → resume (acceptance 5, 7)
- [x] 3. Airshow re-eval with context + Thorough → compare against M0 (aircraft share, crowd share, F-35 coverage)
- [x] 4. Analysis modes Quick/Balanced/Thorough/Custom (ANALYSIS_MODES.md): per-mode detectors, tile density, LRF proxies in Quick, estimates
- [x] 5. Hierarchical summaries shot → day → trip (context changes re-run summaries only)
- [x] 6. Storage placement split/external (macOS and Linux detection), artifact store relocation, DB snapshots via the backup API, cloud placeholders, read-only folders (acceptance 1, 2)
- [x] 7. Project lifecycle: reopen, relink by fingerprint, new/missing/changed files, lease locks with read-only open (acceptance 3)
- [x] 8. Camera profiles insta360, nikon, dji and the unsupported-reason catalog (acceptance 4: partial, see Q-3 and the M1.8 log line)
- [x] 9. Photos: HEIC/JPEG/NEF/DNG ingest, Live Photo pairing, bursts, photo+video moments, photos in mosaics and vision (licence-clean decoders)
- [x] 10. Clock correction (per-device offsets, CLI) and colour: per-profile hints, user LUTs for log sources
- [x] 11. Hybrid search: SigLIP text→image + FTS5, RRF; API and CLI
- [x] 12. Hardware probe and benchmark → estimates; worker pool resource classes and per-provider rate limits
- [x] 13. Scale: the 40-hour synthetic project, bounded memory, list API < 300 ms (acceptance 6)
- [x] 14. M1 acceptance suite, `make eval`, `docs/reports/M1.md`; then continue to M2

## Carry-forward notes

- M2 follow-ups from step 1: the 1280×800 minimum viewport (`min-width` on the app shell) lands with S0 in step 5; the inline pre-paint theme script is allowed by its CSP hash (done in 3a).
- CPU worker slots are threads: Python-heavy per-frame work contends for the GIL (40-hour run: summed task time ≈ 5× wall on 5 slots). Consider process-based CPU slots with the M2 desktop packaging (ADR 0031).
- Pass `allow_gpl_ffmpeg` into media_tools instead of reading storage from media/; consider integer micro-USD for usage costs.
- A job paused at its cost limit needs a way to raise that job's `cost_limit_usd` before resuming (S9/S20, API `resume` parameter).

- Similarity groups are rebuilt (new ids) whenever their key changes; once dispositions or user decisions refer to groups, reference segments or give groups stable identity (invariant 10).

- Step 12: calibrate `library.similarity.MAX_DISTANCE` (0.06) and `segments.VISUAL_CHANGE` on the real corpus; synthetic frames are degenerate for SigLIP (25% of pairs ≥ 0.94).
- `media.telemetry` re-runs (and ends skipped) on every analysis for assets without GPMF; cheap, but could cache a 'no telemetry' artifact.

- Artifact GC: old `frame`/`motion`/proxy artifacts stay when keys change (M1 storage cleanup).
- Dev note: tests share Whisper/SigLIP weights in MosAic's real app-data `models/` folder (`MOSAIC_MODELS_DIR`), so they download once.

- Dev gotcha: an auto-started worker lives ~20 s after its last job and keeps running the code it loaded; wait or kill it after code changes.
- Follow-ups from LUTs (M1.10b): pass the source's colour matrix to the RGB conversion before `lut3d` (untagged HD log footage would use BT.601); key audio analysis on a proxy key without the LUT (a LUT change re-transcribes today); log-curve hints from real Apple Log / N-Log / D-Log M samples (Q-3).
- Follow-ups from photos (M1.9a): vision prompt wording for stills (photos get 0 s segment lines); a HEIC MakerNote content-id test (no HEIC encoder for fixtures); tiled DNG previews; scaled HEIC decode for large photos; pack several photos per contact sheet (one vision call per photo today; ADR needed); rename the corpus `expect_deferred` flag; photos in L3 review and scene summaries.
- Follow-ups from lifecycle (M1.7): asset re-key when a file is renamed and a different new file takes its old path (group order; process relinked rows first); write routes on a project never `/open`ed take an untracked lease (hold it in `Leases`); map OSError from an unreachable share to 503; relink preview for S0 (M2).
- Follow-ups from placement (M1.6): surface "a newer snapshot from another computer is waiting" in project status (UI, M2); shorter open-lock wait for API requests (~5 s) than for the worker; a ProjectBusyError in the worker should defer the task, not fail it; Windows locks (M3).
- M1 follow-ups from summaries (M1.5): flag in the M1 report that acceptance 5 is read as footage-analysis calls (ADR 0021; alternative: lazy summary refresh); check the context digest before the day loop; keyed shot/scene summary rows; bound the trip call for very long trips (week level) and the day call size (~80 items); tests for the highlight retry path, the unconfigured-summarizer skip and the CLI context/summary commands; summarizer calls in estimates.
- M1 follow-ups from analysis modes (M1.4): LRF first-frame PTS alignment check in `lrf_matches` (a one-frame offset passes today); SQL aggregates in `library/estimate.py` and a scoped photo count for deepen estimates; move `_project` to `app/deps.py`; hypothesis test for `plan_samples`/`threshold_cuts`.
- M1 follow-ups from step 4: Apple Log / GoPro flat `log(<name>)` color hints; Live Photo pairing by the still's own content identifier; relink-by-fingerprint probe keys.
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
- 2026-10-05 · M1.5 · Hierarchical summaries: composed shot/scene summaries, AI day and trip summaries with the `summarizer` capability (Haiku; inherits), keyed and bounded; context changes re-run summaries only (API and CLI); `GET /summaries`, `mosaic summary` (ADR 0021)
- 2026-10-05 · M1.6 · Split and external placement: live DB and cache in app data for network/cloud/read-only folders, backup-API snapshots copied into the folder at every project-level checkpoint and on close (never opened by SQLite there), seeding from a snapshot, external projects found by folder fingerprint, `mosaic init --placement` with relocation (ADR 0022; acceptance 1, 2)
- 2026-10-05 · M1.7 · Project lifecycle: scan relinks files by content fingerprint (moved folder: no re-probe, no re-analysis; renamed files keep their record), `POST /relink {choose_folder}`, project leases (`.lock`, holder/host/pid/expiry; read-only open; take-over; renewal; `lock.lost`), `POST /open`/`/close`, `mosaic lock` (ADR 0023; acceptance 3)
- 2026-10-05 · M1.8 · Camera profiles insta360 (flat full; raw 360 analysis_only through a v360 forward view, lens pairs, LRV), dji (chapters by numbering + continuous time, LRF/SRT), nikon_z, GoPro timelapse flag, unsupported catalog with fixes; analysis_only kept out of edits; probe/2 reclassifies older projects; synthetic camera fixtures + real GoPro/iPhone classification (ADR 0024). Acceptance 4: partial — Insta360/DJI/Nikon video only synthetic (Q-3), no real GoPro chapter fixture, Live Photos with step 9
- 2026-10-05 · M1.9a · Photos: JPEG/HEIC (pi-heif, decode-only LGPL)/NEF·DNG·ARW·CR2 embedded previews with a bounded TIFF walk, EXIF time with offset, Live Photos paired by Apple content identifier, photos as one-frame clips (photo.analyze, photo.segment with its own vector index) through embed, mosaics, vision and still-aware dispositions; kept out of edits and video similarity; mosaics track the key behind their rows (ADR 0025)
- 2026-10-05 · M1.9b · Photo bursts (per camera, under 1 s apart, similar; best non-rejected frame) and photo + video captures (within 10 s and similar, merged per shared clip), sub-second photo capture times (photo-probe/2), `photo_group` tables, L1 `library.moments` stage (ADR 0026)
- 2026-10-05 · M1.10a · Devices and clock correction: device table, raw vs corrected capture times (offsets apply instantly, no re-analysis), L1 `library.clock` suggestions from cross-device evidence pairs, devices API and `mosaic clock` (ADR 0027)
- 2026-10-05 · M1.10b · LUTs for log footage: per-device .cube LUT (validated, copied into the artifact store by content), lut3d first in proxies and before scaling in final renders, keys change only for LUT devices, devices API `lut_path`/`clear_lut` and `mosaic device --lut` (ADR 0028)
- 2026-10-05 · M1.11 · Hybrid search: SigLIP text embeddings (same pinned weights), FTS5 index over descriptions/tags/transcripts rebuilt by `library.search_index` at the end of every chain, reciprocal rank fusion, search + suggestions API and `mosaic search` (ADR 0029)
- 2026-10-05 · M1.12 · Hardware probe (cores, memory, working hardware encoders, fingerprint), `system.benchmark` (generated 4K clip through the real proxy builder, frame pass and embedder; stored per computer; first analysis on a machine runs it), benchmark-based wall-time estimates with `basis`, worker slots sized from the probe (`workers.*` overrides), per-provider AI rate limits (`ai.rate.*`), `mosaic hardware`, `/system/info`, `POST /projects/{pid}/benchmark` (ADR 0030); eval budgets were already job cost limits
- 2026-10-05 · M1.13 · 40-hour synthetic project (`mosaic-dev gen-long`, lazily generated in .cache/long-40h), offline fake embedder, `GET /projects/{pid}/library` keyset pages by day or camera, acceptance 6: L0/L1 of 40 h in 922 s with a 500 MB worker peak, slowest list page 18.6 ms (ADR 0031)
- 2026-10-06 · M1.14a · Migrations in one real transaction (driver autocommit + explicit BEGIN, FKs off, foreign_key_check before commit): fixes upgrading populated projects found by `make eval`; Dubai M1 eval 15 events, +0 frames, must-include 7/7
- 2026-10-06 · M1.14 · M1 report: acceptance 1, 2, 3, 5, 6, 7 met; 4 partial (Q-3); Airshow and Dubai evals on the final code
- 2026-10-06 · M1.14b · Airshow M1 eval after the owner-approved removal of the leaked empty table: upgraded cleanly, 43 events, +0 frames, 116 deep reviews, aircraft 79 % / crowd 2 %, 0/92 must-exclude violations
- 2026-10-06 · M2.1 · Web UI foundation: Vite + React 19 + TS 5.9 strict, Tailwind 4 `@theme` generated from tokens.json (checked in tests), bundled Geist fonts via Fontsource (the `geist` package pulls Next.js + LGPL libvips), dark/light themes, Storybook 10, openapi-fetch client generated from the API schema (kept current by a test), shipped-license test, API serves the built UI with SPA fallback (ADR 0032)
- 2026-10-06 · M2.2a · Design-system components with stories per state (both themes): primitives, media chips/controls/ClipTile, system rows; AI-vs-you test (acceptance 8); tailwind-merge taught the token type sizes (it dropped colour classes next to `text-caption`); generated npm license table in LICENSES.md; on-media tokens and `micro`/`tag` type, footage overlays always in dark token values (ADR 0033)
- 2026-10-06 · M2.3a · Server-mode sign-in: one admin (Argon2), hashed session and CSRF tokens in the control DB, HttpOnly/SameSite=Strict/Secure cookie, CSRF header on writes, 5-failure lockout with countdown, security headers (CSP allows the hashed theme script), S2 screen + auth gate; desktop mode unchanged (ADR 0034)
