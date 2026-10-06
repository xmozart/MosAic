# Architecture

## 1. Topology

One logical application, deployed two ways.

```text
React/TS UI  ──HTTP + SSE──>  FastAPI (API + services)
                                   │
          ┌───────────────┬────────┴────────┬──────────────────┐
          v               v                 v                  v
   Job DAG store     Control DB       Project DBs         Secret store
   (control DB)      (SQLite)         (SQLite, per        (keyring /
          │                           project, placed     env / Docker
          v                           by policy §4)       secrets)
   Worker processes (resource classes: cpu, gpu_encode, ai_api, io)
          │
          ├─ FFmpeg / ffprobe (subprocess)
          ├─ numpy/SciPy image metrics (ADR 0008)
          ├─ faster-whisper, SigLIP embeddings (local)
          └─ AI provider adapters (cloud / local)
```

- **Server mode:** a Linux Docker image. The API and N worker processes run in one container or several. Media roots are bind-mounted. v1 is single-user with local authentication.
- **Desktop mode (Mac first, Windows later):** a Tauri shell launches the same backend as a sidecar on `127.0.0.1` with a random port and a per-launch token. Workers are local processes.

HTTP handlers never perform media or AI work. They create, query and cancel jobs. Progress is pushed to the UI over Server-Sent Events.

## 2. Repository layout

Python package `mosaic` lives in `backend/mosaic/` (ADR 0004):

```text
backend/mosaic/
  app/            FastAPI routers, auth, SSE
  core/           domain models, time types, config hierarchy, provenance
  storage/        placement policy, artifact store, DB sessions, snapshots
  jobs/           DAG store, scheduler, worker runtime, leases
  media/          probe, camera profiles, proxies, sampling, scenes, metrics, ffmpeg builders
  audio/          VAD, transcription, loudness, events
  ai/             provider adapters, prompts/, schemas, rate limits, cost
  library/        segments, similarity, embeddings, search, summaries
  editing/        planner, selector, solver, refiner, critic, versions
  render/         chunk renderer, assembler, color, audio mix
  cli/            thin CLI calling the same services
  devtools/       synthetic corpus generator, frame barcode (developer only)
frontend/
desktop/          Tauri project
docs/
tests/            unit, integration (synthetic media), evaluation
```

## 3. Deployment and process model

| Concern | Server | Desktop |
|---|---|---|
| Bind address | Configurable, behind a reverse proxy with TLS | `127.0.0.1` only |
| Auth | Single admin account, Argon2 password hash, HttpOnly SameSite cookie, CSRF token | Per-launch random bearer token passed from Tauri. Host-header allowlist protects against DNS rebinding. |
| Folder selection | Server-side browser limited to configured media roots | Native folder picker |
| Secrets | Env vars, Docker secrets, or an encrypted file keyed by an install master key | OS keyring via Python `keyring` (Keychain / Credential Manager); also used in development (ADR 0003) |
| Workers | Configurable counts per resource class | Auto-sized from CPU/GPU probe |

## 4. Storage placement policy

When a project is created, detect the filesystem class of the footage folder:

| Class | Detection | Placement |
|---|---|---|
| `local` | Local or external disk (APFS, HFS+, exFAT, NTFS, ext4…) | **In-folder.** Descriptor at `<root>/.mosaic-project.json`; live DB, cache and exports under `<root>/MosAic/`. |
| `network` | macOS `statfs` type `smbfs`, `nfs`, `afpfs`, `webdav`; Windows `DRIVE_REMOTE`; Linux `/proc/mounts` `cifs`/`nfs` | **Split.** Live DB and cache in the local app-data workspace. Descriptor, DB snapshots, edit JSON and exports written to the folder. |
| `cloud_synced` | Paths under `~/Library/Mobile Documents`, `~/Library/CloudStorage/*`, known Dropbox/OneDrive/Google Drive roots; Windows cloud-file attributes | **Split.** Proxies and cache are never written to the folder. |
| `read_only` | Write-permission check fails (ADR 0005) | **External.** Everything lives in the local workspace. The project is keyed by folder fingerprint. |

Server exception: if the server host owns the disks (for example, the app runs on the NAS itself), the mount is `local` from the server's point of view.

Rules:
- Users may override placement in Advanced settings. Choosing a live DB on a `network` or `cloud_synced` path is refused with an explanation.
- **Snapshots** use the SQLite online backup API to write `<root>/MosAic/project.db` at checkpoints: analysis stage complete, edit committed, and project close. When a folder containing only a snapshot is opened elsewhere, the snapshot seeds a new live DB.
- **Cloud placeholders.** Before probing, check whether each file is locally present. Offline files are listed with total size and an offer to download them first. Probing must never trigger silent downloads.
- The **artifact store** abstracts locations. Code asks for `artifact(kind, key)` and never builds paths itself.
- Split and external projects keep their live DB and cache in app data under `projects/<project_id>/`; external projects also keep their descriptor and outputs there and are found by folder path or folder fingerprint (ADR 0022).

Project descriptor, `<root>/.mosaic-project.json` (always small, written when the folder is writable):

```json
{
  "format_version": 2,
  "project_id": "01J9ZK3Q6N8T2V4X5Y7A9B1C3D",
  "name": "Costa Rica 2026",
  "workspace": "MosAic",
  "placement": "in_folder",
  "created_at": "2026-09-29T20:00:00-04:00"
}
```

## 5. Data model

### 5.1 Control DB (app-level)

The control DB lives in the OS app-data directory and has its own Alembic tree. It also keeps an edit-ID → project index, so `/edits/{eid}` routes resolve.

Tables:
- **Installation:** `installation`, `user` (exactly one in v1, but the ID is always carried), `project_registry` (project_id, root path, placement, last opened).
- **Settings and providers:** `user_preferences` (including `eval.corpus_dir`), `provider_profile` (non-secret: capability → provider, model, mode), `secret_ref`, `usage_record`. Edited through the `mosaic config` CLI and the `/settings`, `/providers` and `/secrets/*` API (ADR 0003).
- **Job DAG:** `job`, `task`, `task_dependency`, `lease`. `job` carries `user_id`; `task`, `task_dependency`, `lease` and `task_event` are owned through their job. A `worker` table records live worker processes.

### 5.2 Project DB (portable)

Asset hierarchy:

```text
MediaFile     physical file: relative path, size, mtime, fast fingerprint (size + head/tail hash), probe JSON
   │  (many-to-one)
Asset         logical item: kind = video | photo | live_photo | audio | unsupported
   │          (a GoPro/DJI chaptered recording is ONE video Asset over several MediaFiles)
Shot          contiguous range between detected cuts (video) or the whole item (photo)
   │
Segment       editorially coherent sub-range of a shot, typically 1–20 s; the unit of AI analysis and selection
   │
Moment        optional point of interest inside a segment (reaction peak, reveal, spoken line)
```

Other tables:
- **Sampling and analysis:** `sample_frame`, `mosaic`, `mosaic_tile` (tile index ↔ sample_frame), `visual_observation`, `transcript_word`, `transcript_segment`, `audio_event`, `tech_metric`, `embedding`.
- **Library:** `similarity_group`, `disposition` (USE/MAYBE/REJECT with reasons and source ai or user, anchored to its source range so user decisions survive re-segmentation, ADR 0013), `user_rating`, `user_note`, `user_tag`, `include_rule` (always/never), `lock`, `trip_context`, `summary` (shot, scene, day and trip levels).
- **Labeling (S24):** `labeling_question` (kind: place, same_person or event; candidate asset ids; status), `person_link` (asset ids linked to a trip-context person label). This is a user-confirmed link only: no face embeddings or biometric data are stored.
- **Devices and time:** `device` (make, model, serial or camera profile; `clock_offset_ms`, its source, the zone adopted from a reference device, `lut_path`), `device_suggestion` (suggested offset, agreeing evidence pairs), and on `asset`: `device_id`, `capture_time_raw` (as the file says) and `capture_time` (corrected; read by everything that orders or groups by time) (ADR 0027).
- **Photos:** `asset.live_motion_enabled` for Live Photos; `photo_group` (kind `burst`, with `best_segment_id`, or `capture`: photos and video segments of one moment) and `photo_group_member` (ADR 0026).
- **Editing:** `edit`, `edit_version`, `edit_draft_op`, `finding` (severity, timecode, text, suggested op, status: open, applied or ignored, applied_in_version), `render`, `provenance`.
- **Control DB additions:** `saved_preset` (named edit-request templates per user), `local_model` (name, size, checksum, status).

Every AI or algorithmic row links to a `provenance` row with:
- provider, model and model version
- prompt version and algorithm version
- input artifact keys and config hash
- tokens, cost and created_at

### 5.3 Segment record (canonical example)

```json
{
  "segment_id": "seg_000451",
  "asset_id": "ast_0123",
  "range": {
    "start": {"ticks": 3789000, "tb": "1/90000"},
    "end":   {"ticks": 4662000, "tb": "1/90000"}
  },
  "usable_range": {
    "start": {"ticks": 3834000, "tb": "1/90000"},
    "end":   {"ticks": 4590000, "tb": "1/90000"}
  },
  "capture_time": "2026-07-15T17:32:10-06:00",
  "visual": {
    "description": "Drone pushes toward a waterfall in dense jungle.",
    "subjects": ["waterfall", "jungle"],
    "shot_type": "drone_establishing",
    "camera_motion": "push_in_slow",
    "interest": "high",
    "composition": "good"
  },
  "audio": {"speech": false, "natural_sound": "waterfall", "quality": "good"},
  "technical": {"sharpness": "good", "stability": "excellent", "exposure": "good"},
  "editorial": {
    "status": "USE",
    "status_source": "ai",
    "roles": ["establishing", "hero"],
    "rejection_reasons": []
  },
  "provenance_id": "prov_00981"
}
```

AI qualitative scores use **ordinal scales**: `poor | fair | good | excellent`, or `low | medium | high`. Deterministic metrics are stored as raw values plus a project-normalized percentile. Never ask a model for two-decimal floats.

## 6. Timebase

- `SourceTime` is integer ticks in the stream time base. It is always relative to the stream's first presentation timestamp after edit lists are applied. Store `start_pts` per stream on MediaFile.
- For a chaptered Asset, logical time is the concatenation of its files. Store a mapping table from logical time to (file, local ticks).
- `TimelineTime` is integer frames at the edit's timeline rate. Audio positions are samples at 48 kHz.
- Conversions live only in `core/time.py`, use exact rational arithmetic (`fractions.Fraction`), and have property-based tests.
- **Proxy mapping.** Proxies are CFR and derived from source PTS. Each proxy stores a table mapping proxy frame to source ticks (or a verified affine map for CFR sources). Analysis results are always written back in source ticks.
- **Frame-rate conform (render).** A source rate equal to the timeline rate passes through. Otherwise, use nearest-frame (default) or frame blend (option). Sources at 100 fps or higher are marked `hfr` and may be conformed as slow motion when the selector or user requests it. VFR sources are resampled by PTS, never by frame count.

## 7. Job DAG

- `job` is a user-visible unit, such as an analysis run, an edit generation or a render. `task` is an idempotent unit of work with `kind`, `resource_class`, `input_keys`, `output_key` and `status` (`pending | ready | leased | done | failed | skipped | cancelled`).
- **Scheduler.** Tasks become `ready` when all dependencies are `done`. Workers atomically lease one ready task of their class using `UPDATE … RETURNING` with a lease expiry and heartbeat. Expired leases return the task to `ready`.
- **Idempotency.** Before running, a worker checks whether the artifact for `output_key` exists and is valid. If it does, the task is marked done without work. This makes resume after a crash trivial.
- **Rate limits.** `ai_api` tasks pass through per-provider token buckets (requests per minute and tokens per minute) plus a cost ceiling per job. (M0: the cost ceiling is enforced by atomic reservation and provider SDK retries handle 429s; the token buckets arrive with heavier parallel use in M1, ADR 0012.)
- **Per-project write serialization.** Project DB writes go through a single writer per project: a worker-side queue, with SQLite WAL mode only on `local` placement.
- **Progress** is aggregated per job: stage, current item, done/total, and ETA only after at least 10% of tasks have completed. It is published over SSE.
- **Executor interface.** `Executor.submit / cancel / heartbeat` isolates this design so a distributed executor can replace local processes later without schema changes.

## 8. Analysis pipeline

Stages per asset, all tasks:

1. **probe.** Run ffprobe plus camera-profile parsers (`MEDIA_SUPPORT.md`) to produce MediaFile and Asset rows.
2. **group.** Chapter grouping, Live Photo pairing and sidecar association. (Bursts and photo + video captures need embeddings and dispositions, so they are grouped later, in the L1 project stage `library.moments`; ADR 0026. Clock-offset suggestions follow in the L1 stage `library.clock`; ADR 0027.)
3. **proxy.** 720p H.264 8-bit SDR Rec.709 CFR, at the source rate halved until it is at most 30 fps (ADR 0007), one proxy per asset over its logical timeline. HDR and log sources are tone-mapped or have a LUT applied (a device's LUT replaces tone mapping; ADR 0028). Camera LRF/LRV files are associated and validated in every mode, but used as proxies only in Quick mode. This proxy is required because it is also the browser playback format.
4. **shots.** Adaptive content detector (PySceneDetect's algorithm, ported to numpy; ADR 0008) on the proxy. Add forced subdivision for long static shots.
5. **samples.** Scene-change frames and fixed-interval frames (ADR 0008), merged and deduplicated by perceptual hash and SigLIP embedding distance. Scene-change frames and user-marked frames are always retained.
6. **tech metrics.** Sharpness (variance of Laplacian), exposure (histogram clipping), noise estimate, shake (gyro from GoPro GPMF or Insta360 when present, stored as `shake_gyro`; otherwise optical-flow jitter, `shake`), freeze or duplicate frames, and lens obstruction.
7. **audio.** VAD, then transcription with word timestamps, loudness, clipping and wind estimate.
8. **segments.** Split shots into Segments using motion changes, speech boundaries and sample clustering. Compute `usable_range` by trimming camera-start and camera-stop wobble, as detected from motion.
9. **embeddings.** Local SigLIP image embeddings per sample, then pooled per segment.
10. **mosaics.** Build contact sheets per the active analysis mode, sized to the vision provider's effective image size (ADR 0013). Tiles come from one asset or shot where possible, so the model sees continuity. Each tile has a burned-in label (`T07 · ast_0123 · 00:02:14.3`) and a sidecar mapping. The model must reference tiles by index (`T07`), and code resolves the index to source ticks.
11. **vision.** A structured observation for each segment. The mosaic is the transport format; the segment is the unit. Skipped with a "not configured" reason when no vision provider can be used; dispositions then use rules only (ADR 0013).
12. **similarity.** Cluster segments by embedding (M0) and later visual observation, and pick the recommended best per cluster. Leader clustering against group seeds prevents chaining (ADR 0011).
13. **disposition.** Deterministic rules (technical failure, accidental recording) plus AI judgement produce USE/MAYBE/REJECT with reasons.
14. **summaries.** Shot → scene → day → trip, including trip context when present. Summaries are cheap to regenerate when context changes.

Analysis levels (`ANALYSIS_MODES.md`) decide which stages run and at what density. Artifacts are keyed per level so deepening reuses everything already computed.

## 9. Editing pipeline

```text
EditRequest + TripContext(optional) + locks/ratings
   │
   v
Candidate retrieval   (deterministic filters + vector search; caps the LLM context)
   │
   v
Story planner (AI)    → beats: ordered sections with intent, target share of duration, candidate pool
   │
   v
Shot selector (AI)    → per beat: ordered selections {segment_id, role, priority 1–5,
                         length: short|medium|long|hold, audio_intent, alternatives[]}
   │
   v
Solver (code)         → exact durations and positions: meets target ± tolerance,
                         min/max shot length from pace, drops lowest-priority shots or trims
                         to fit, honours locks as hard constraints, reports infeasibility
   │
   v
Cut refiner (code)    → snaps in/out to: inside usable_range, not inside a word,
                         after motion settles, before a camera drop, never across a shot cut;
                         (later) beat/phrase grid
   │
   v
Deterministic critic  → repetition (same similarity group within N shots), jump cuts
                         (adjacent same-asset near-contiguous), dialogue truncation,
                         duration error, day/beat coverage, shot-type balance
   │
   v
AI critic (optional)  → story coherence, opening/ending strength; outputs structured
                         suggestions that re-enter at selector or solver
   │
   v
Edit version (immutable) + proxy preview render
```

Concrete M0 choices (pace table, retrieval cap, solver, refiner, jump-cut handling and metric definitions) are in ADR 0015.

The AI never emits `timeline_in` or `timeline_out`. Selector output example:

```json
{
  "beat_id": "beat_02",
  "selections": [
    {
      "segment_id": "seg_000451",
      "role": "establishing",
      "priority": 5,
      "length": "long",
      "audio_intent": "natural_sound_low",
      "reason": "Clearest reveal of the waterfall; opens the jungle day.",
      "alternatives": [
        {"segment_id": "seg_000455", "why_not": "Same pass, slight horizon tilt"}
      ]
    }
  ]
}
```

Resulting timeline event (solver and refiner output):

```json
{
  "event_id": "evt_0007",
  "kind": "video",
  "asset_id": "ast_0123",
  "source_in":    {"ticks": 3852000, "tb": "1/90000"},
  "source_out":   {"ticks": 4356000, "tb": "1/90000"},
  "timeline_in":  {"frames": 311, "rate": "30000/1001"},
  "timeline_out": {"frames": 479, "rate": "30000/1001"},
  "speed": "1/1",
  "transform": {"crop": null, "reframe": null, "stabilize": false},
  "audio": {"source_enabled": true, "gain_db": -12, "fade_in_frames": 6, "fade_out_frames": 6},
  "transition_out": {"type": "cut"},
  "role": "establishing",
  "origin": {"selection_ref": "beat_02#0", "locked": false}
}
```

Still-photo events use `"kind": "still"` with `duration` in frames and a `motion` object (start/end crop rectangles for pan and zoom, plus easing).

The model stays OTIO-mappable: tracks, clips, transitions, markers and metadata dictionaries. Exporters come later.

## 10. Rendering

- **Chunk renderer.** Each timeline event is rendered to a normalized mezzanine at the timeline format (resolution, rate, color space, 48 kHz stereo). Chunks include handles for transitions. The cache key is the event hash plus the render profile, so unchanged events are reused across versions. Chunks render in parallel.
- **Assembler.** Concatenation, transitions (xfade / acrossfade over handles), audio mix (source audio, generated silence for silent sources, music bed later) and loudness normalization.
  - Loudness targets: −14 LUFS integrated for web (default) or −23 LUFS (EBU R128) for TV.
  - True peak ≤ −1 dBTP.
- **Preview** renders from proxies at 720p with a fast hardware encoder. **Final** renders conform to originals at the requested format.
- **Color, v1.** The working space is SDR Rec.709.
  - HLG and PQ sources (including iPhone Dolby Vision profile 8.4, whose HLG base layer is used) are tone-mapped with zscale+tonemap, or libplacebo when available.
  - Log sources (Apple Log, N-Log, D-Log M, GoPro flat) use a per-camera-profile LUT. The user supplies vendor LUTs unless redistribution is licensed.
  - HDR output is a later milestone.
- **Encoders** are chosen from the capability probe (VideoToolbox, NVENC, QSV, AMF). Software encoding is used only if the user has installed an FFmpeg that provides it.
- All FFmpeg commands come from typed builders. Command, stderr and duration are logged to the diagnostics store.
- M0 details (cutting, audio alignment, mezzanine, loudness passes, profiles) are in ADR 0016.

## 11. AI provider layer

Capability interfaces:
- `VisionAnalyzer`
- `StoryPlanner`
- `ShotSelector`
- `Critic`
- `Transcriber`
- `Embedder`

Each adapter declares:
- max effective image dimensions and max images per request (for example, a provider that downscales to about 1.5k px long edge makes 4K mosaics pointless)
- whether video input is supported
- structured-output support, context window, and a cost table
- a local or cloud flag

Behaviour:
- **Mosaic geometry** is chosen from the adapter's limits and the analysis mode, not from a fixed setting.
- **Structured output.** Use the provider's JSON-schema or tool mode when available. Validate with Pydantic, retry once with the validation errors, then fail the task.
- **Privacy.** In `local_only` mode, cloud adapters are unavailable and the UI states which features are missing. GPS coordinates are never sent to cloud providers unless the user enables it; coarse place names from trip context are allowed.
- **Provider selection is configuration.** Each cloud capability's provider and model come from `provider_profile`, not code (ADR 0003). Prompts and schemas are provider-neutral; only `ai/adapters/<provider>/` imports a provider SDK. A provider must support image input and structured output to serve `VisionAnalyzer`.
- **v1 providers.** Anthropic is the default for vision and reasoning, with local faster-whisper (STT) and local SigLIP (embeddings). The installed Claude Code and Codex apps can serve every AI capability through the owner's own sign-in, with no API key (`claude-cli`, `codex-cli`, ADR 0014); they count as cloud for `local_only`. Adapters for other providers are added when the owner selects one. The interfaces must admit others without changes.

## 12. Search

- **Hybrid search.** SigLIP text→image similarity over sample embeddings, plus full-text search (FTS5) over descriptions, tags and transcripts. The two result sets are merged with reciprocal rank fusion.
- Vectors live in sqlite-vec inside the project DB, one index per (owner kind, model, dimension): sample, segment and photo-segment vectors are indexed separately (ADR 0025). The index mirrors the `embedding` table, whose rows are rebuilt when the producing stage's key (which includes the algorithm version) changes. A model change creates a new index; it does not overwrite the old one (ADR 0011).

## 13. Edit versioning

- An `edit` has a **draft** (a mutable op log: trim, reorder, replace, lock and so on, with undo/redo) and **versions** (immutable snapshots).
- A version is created on AI generation, AI revision, explicit user save, and before render.
- Each version stores parent, creator (`user | ai | system`), reason, config snapshot hash and provenance references.
- The edit JSON export `edits/<edit_id>/v<NNN>.json` is written on version creation.

## 14. Security

- **Paths.** Canonicalize every path. Reject paths outside the project root or the configured media roots, and reject symlinks that escape them. Browser clients receive project-relative paths only.
- **Secrets.** Redact them in logs and exceptions. Never persist Authorization headers. Pass keys to subprocesses via environment or stdin, never argv. The UI shows only `configured` and the last 4 characters.
- **Desktop API.** Require the per-launch token on every request, allow only `127.0.0.1` and `tauri://` in CORS, and check the Host header.
- **Project locks.** A lease file `MosAic/.lock` (holder installation, host, pid, expiry); the file is the single source of truth (ADR 0023). Read-only open never takes the lock. A stale lease can be taken over after expiry; a live lease can be force-unlocked only after a warning.

## 15. Packaging

- **Server.** A multi-arch Docker image (amd64, arm64) with an LGPL FFmpeg. Include compose examples with media-root bind mounts and optional NVIDIA runtime.
- **Mac desktop.**
  - Tauri 2 app with a Python sidecar built from python-build-standalone (or PyInstaller) and a bundled LGPL FFmpeg.
  - Whisper and SigLIP models downloaded on first use, with checksums.
  - Code-signed and notarized, universal or arm64 first.
- **Windows desktop** comes later. The code must already avoid POSIX-only assumptions: use `pathlib`, no `fork`-only multiprocessing, and handle long paths.

## 16. Observability

- Structured JSON logs with job_id, task_id and project_id.
- A diagnostics panel showing FFmpeg commands, stderr, AI request metadata (model, tokens, cost, latency, never payload secrets) and task timings.
- A "diagnostic bundle" export that is redacted by construction.

## 17. Scale

- Design targets: 5 minutes to 40+ hours of footage, and up to 20k photos per project.
- The UI paginates and virtualizes every list.
- Tasks are per asset or per mosaic, never per project.
- The LLM never receives the whole library. Retrieval and hierarchical summaries bound the context.
- Performance tests (M1) use synthetic long projects.
