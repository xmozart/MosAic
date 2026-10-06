# API Map

These are the REST endpoints and SSE events the screens need.

- All paths are under `/api`.
- All long operations return `202 {job_id}`.
- Times in payloads follow `CLAUDE.md` invariant 3. Responses may add a derived `display` string, such as `"02:14.3"`.
- Lists are cursor-paginated: `?cursor=&limit=` returns `{items, next_cursor}`.
- Every request is authorized through `authz.check`.

## Auth & system

| Method | Path | Used by |
|---|---|---|
| GET | `/auth/status` (public: `{mode: desktop\|server, setup_required, signed_in}`) | S2, S0 |
| POST | `/auth/setup` · `/auth/login` (public; set the HttpOnly SameSite=Strict session cookie and the readable `mosaic_csrf` cookie; 401 wrong password, 429 with `Retry-After` after 5 failures) · `/auth/logout`. Server mode: every other `/api` request needs the session, and writes need `X-CSRF-Token` (ADR 0034) | S2 |
| GET | `/system/info` (mode: desktop/server, version, hardware probe with fingerprint, encoders, `workers` slots per resource class, `benchmark` or null, `rate_limits` per provider; ADR 0030) | S0, S22 |
| POST | `/projects/{pid}/benchmark?force=` → `{job_id}`: measure this computer in the project's queue (ADR 0030) | S8, S22 |
| GET/POST/DELETE | `/admin/media-roots` (server only; `{id, label, path, source: admin\|env}`; POST `{path, label?}` → 201, 422 for a relative or missing folder; ADR 0035) | S22 (admin) |
| GET | `/fs/browse?root=&path=&cursor=` (server only; without `root`: the roots, no paths. With it: `{root, path, crumbs, here, here: {counts, has_project}, items: [{name, path, counts: {videos, photos, folders, complete}|null, has_project}], next_cursor}`; counts are recursive, capped at 20,000 entries per folder, and `null` once the 2 s listing budget is spent; paths relative to the root; 403 outside it, 404 unknown; ADR 0035, 0039) | S4 |

## Settings & secrets

| Method | Path | Used by |
|---|---|---|
| GET/PATCH | `/settings` (returns `{key: {value, source}}` with source = default/user) | S22 |
| GET/PATCH | `/providers` (capability → provider/model/mode, source default/user/inherited, ADR 0019) | S1, S22 |
| PUT | `/secrets/{ref}` (write-only; returns `{configured, last4, store: keychain\|encrypted_file\|environment\|docker, from_deployment}`; a server needs its master key to save, ADR 0036) | S1, S22 |
| DELETE | `/secrets/{ref}` (removes the key the user entered; a deployment key is used again) | S22 |
| POST | `/secrets/{ref}/validate` | S1, S22 |
| GET | `/models/local` · POST `/models/local/{name}/download` (job) | S1 |

## Projects

| Method | Path | Used by |
|---|---|---|
| GET | `/projects` (recents from the control DB only: `{id, name, placement, fs_class, folder: {root, path}, missing: true\|false\|null, last_opened_at, card: {clips, photos, footage_seconds, first_date, last_date, cover: [sample ids], analyzed, latest_edit}, status: {state: scanning\|analyzing\|analyzed\|scanned\|not_analyzed, pct?, job_id?, mode?}}`; `missing: null` while a slow folder is still being checked; ADR 0038) | S3 |
| POST | `/projects/preview` `{path}` (desktop) or `{root, path}` (server) → `{name, fs_class, reason, placement, counts: {videos, photos, folders, complete}, project_id}` (no writes; counts and folders only, nothing probed; ADR 0039) | S4 |
| POST | `/projects` `{path \| root+path, name?, placement?}` → `{id, name, created, placement, scan_job}` (a scan-only job; an existing project is opened, `created: false`) | S4 |
| POST | `/projects/{pid}/open` `{read_only?, take_over?}` (acquires the lease; `409` `{detail, holder: {host, since, until}}` if open elsewhere; ADR 0023) · `/close` (releases it) | S0, S3 |
| POST | `/projects/{pid}/relink` `{choose_folder?}` (desktop) or `{root, path}` (server; 403 outside the root, 404 refused; 422 if both forms are sent) → `{job_id, root, mode}` (re-scan with the last analysis mode; `409` if the folder is gone and none is chosen; `422` if the chosen folder is not this project's) | S0 |
| GET | `/projects/{pid}/inventory` → `{summary, cameras: [{key, label, kind, device_id, clips, photos, limited, files, footage_seconds, badges, sample_id, clock}], days: [{date, by_camera}], attention: [{kind: unreadable\|limited\|cloud, count, reason, fix, bytes?, group?, example?}], notes: {chaptered_recordings, live_photos, bursts}}` (catalog reasons only) | S5 |
| GET | `/projects/{pid}/inventory/files?kind=unreadable\|limited\|cloud&group=&after=` → `{items: [{id, path, bytes}], next_after}` (S5 "Show files": paths relative to the project folder, 200 per page; `group` from an unreadable row; 404 unknown group; ADR 0040) | S5 |
| POST | `/projects/{pid}/cloud-files/download` → `{job_id}` (reads cloud-only files so the OS downloads them, then rescans) | S5 |
| GET/PUT | `/projects/{pid}/devices` (clock offsets, LUT path; PUT `{devices: [{id, clock_offset_ms \| accept_suggestion \| lut_path \| clear_lut}]}` → `{devices, assets_updated, refresh_job, reanalysis_needed}`; LUTs ADR 0028) · GET `/projects/{pid}/devices/suggestions` (offset, verdict, evidence pairs with `device_sample` and `reference_sample` frame ids; suggestions need the analysis's embeddings; ADR 0027, 0040) | S6, S21 |
| GET/PUT | `/projects/{pid}/trip-context` (PUT returns `summaries_job`: a context change re-runs summaries only) · POST `/trip-context/parse` `{text}` → `{job_id}`; the job's `result.proposal` (`GET /jobs/{id}`) is the proposed structure, saved only by a PUT (ADR 0040) | S7 |
| GET | `/projects/{pid}/summaries?level=day\|trip\|scene\|shot&after_ref=&limit=` (`day`: the trip plus each day; scene and shot are paged by ref, limit ≤ 1000) → `{items: [{level, ref, text, themes?, highlights, subjects?, span?}], next_after_ref}` (ADR 0021) | S10, S16 |
| GET/PATCH | `/projects/{pid}/settings` (effective values with source) | S21 |
| GET | `/projects/{pid}/storage` · POST `/storage/clear-cache` | S21 |
| DELETE | `/projects/{pid}/recent` → 204 (hides the project from recents and releases its lease; nothing is deleted; opening the folder again brings it back; ADR 0039) | S3 |
| DELETE | `/projects/{pid}/workspace` (removes MosAic data; originals untouched) | S21 |

## Analysis & jobs

| Method | Path | Used by |
|---|---|---|
| GET | `/projects/{pid}/analysis/estimate?mode=&scope=` (scope: `trip`, `days:2,3` or `selection:ID,…`; omitted = whole-project run). Returns videos, photos, footage seconds, segments, `l2_calls`, `l3_calls` [lo, hi], `cost_usd` [lo, hi] or null when a model has no price, `storage_bytes`, `wall_seconds` [lo, hi], `basis` (`benchmark` or `default`, ADR 0030), `days` (ADR 0020) | S8, S25 |
| POST | `/projects/{pid}/analysis-runs` `{mode, scope?, overrides?, cost_limit}`; scope `{kind: trip\|days\|selection, days?, segment_ids?}` deepens (mode `balanced` or `thorough`: adds L2 where missing, then L3) and returns `{job_id \| null, candidates, l2_assets, dropped}`; without scope the whole project is analyzed in the mode (`overrides` only with `custom`) | S8, S25 |
| GET | `/jobs?project=&active=` · `/jobs/{id}` (stages, current item, live sample, `cost_usd`, `cost_limit_usd`) | S9, S0 |
| POST | `/jobs/{id}/pause` · `/resume` (optional body `{cost_limit_usd}`: raise the AI cost limit of a job paused at it; must exceed what the job has spent; ADR 0018) · `/cancel` · `/retry-failed` | S9, S20 |
| GET | `/events?project=` (SSE; without `project`: every project, for the rail's activity ring) | all |

SSE event types:

| Event | Payload |
|---|---|
| `job.progress` | `{job_id, project_id, kind, state, pct, stage, item, cost}` |
| `job.stage` | Stage transition |
| `job.state` | running / paused / paused_cost_limit / done / failed / cancelled |
| `analysis.ready_to_browse` | Fired when L0 and L1 are complete |
| `clip.updated` | `{asset_id, fields}` |
| `edit.progress` | `{edit_id, step, beats_planned[]}` |
| `edit.version_created` | — |
| `render.progress` | — |
| `lock.lost` | — |

## Library

| Method | Path | Used by |
|---|---|---|
| GET | `/projects/{pid}/library?group=day\|camera\|similar&filters…&density=` (groups with paginated items). Built in M1 (ADR 0031): `group=day\|camera&cursor=&limit≤200` → `{items, next_cursor, groups}` with keyset pages (items: asset, kind, status, name, group, capture time, duration `{ticks, tb}`, segments, disposition counts, tile `sample_id`; `groups` on the first page); `similar`, filters and density come in M2 | S10 |
| GET | `/projects/{pid}/clips/{aid}` (detail: moments, quality, why, similar, tags, note, used_in) | S11 |
| GET | `/projects/{pid}/clips/{aid}/transcript` | S11 |
| PATCH | `/projects/{pid}/clips/{aid}/decision` `{disposition?, stars?, include?: always\|never\|none, tags?, note?, live_motion?}` | S10, S11 |
| POST | `/projects/{pid}/decisions/bulk` `{asset_ids[], …}` | S10 |
| GET | `/projects/{pid}/search?q=&mode=all\|visual\|speech&limit=` (items: segment, asset, exact start/end, sample, status, score, `matched` reasons; `visual: ok\|unavailable\|off` drives S12's "analysis incomplete" banner) · `/search/suggestions` (the trip's own tags) (ADR 0029) | S12 |
| GET | `/projects/{pid}/labeling-questions` · POST `/labeling-questions/{qid}/answer` | S24 |
| GET | `/media/{pid}/proxy/{aid}` (HTTP range; 404 until a proxy exists) · `/media/{pid}/frame/{sample_id}` (JPEG) · `/media/{pid}/waveform/{aid}` (`{silent, bucket: {ticks, tb}, count, peaks: base64 0–255}`, from the `media.waveform` stage) · `/media/{pid}/filmstrip/{aid}?n=&start_ticks=&end_ticks=` (`{tb, frames: [{sample_id, ticks}]}`) (ADR 0037) | all |

## Edits

| Method | Path | Used by |
|---|---|---|
| GET/POST | `/projects/{pid}/edits` | S13, S14 |
| GET | `/projects/{pid}/presets` · `/presets/{id}/collage` | S14 |
| POST | `/edits/estimate` `{request}` | S14 |
| POST | `/edits/{eid}/generate` (job; emits `edit.progress`) | S14, S15 |
| GET | `/edits/{eid}` (current draft, beats, events, facts) | S16, S17 |
| POST | `/edits/{eid}/draft/ops` `{op}` (reorder, lock, replace, remove, trim, faster/slower) · `/draft/undo` · `/draft/redo` | S16 |
| POST | `/edits/{eid}/versions` (commit draft) · GET `/edits/{eid}/versions` · `/versions/{v}` | S16, S18 |
| GET | `/edits/{eid}/compare?a=&b=` (change list) | S18 |
| POST | `/edits/{eid}/beats/{bid}/regenerate` · `/edits/{eid}/regenerate?scope=story\|all` | S16 |
| GET | `/edits/{eid}/shots/{evt}/alternatives` | S16 |
| GET | `/edits/{eid}/findings` · POST `/findings/{fid}/apply` · `/ignore` · `/findings/apply-all` | S17 |
| POST | `/edits/{eid}/preview` (render job) | S16, S17 |
| POST | `/edits/{eid}/revert` `{version}` | S18 |
| GET | `/edits/{eid}/report?version=` (selection/rejection report and metrics) | S17, CLI `mosaic report` |

## Renders

| Method | Path | Used by |
|---|---|---|
| POST | `/renders` `{edit_id, version, preset, resolution, fps, loudness, include[], dest}` | S19 |
| GET | `/projects/{pid}/renders` · POST `/renders/{rid}/cancel` · `/rerender` · DELETE `/renders/{rid}/file` | S20 |
| POST | `/renders/{rid}/reveal` (desktop only) | S20 |

## Diagnostics

| Method | Path | Used by |
|---|---|---|
| GET | `/diagnostics/tasks?project=&status=` · `/diagnostics/tasks/{tid}` | S23 |
| POST | `/diagnostics/bundle` (redacted export) | S23 |
