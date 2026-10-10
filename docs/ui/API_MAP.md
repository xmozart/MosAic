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
| POST | `/auth/desktop-session` (desktop: `Authorization: Bearer <per-launch token>` → HttpOnly `mosaic_desktop` session cookie; 404 in server mode or without a token; ADR 0057) | S0 |
| GET | `/system/info` (mode: desktop/server, version, hardware probe with fingerprint, encoders, `workers` slots per resource class, `benchmark` or null, `rate_limits` per provider; ADR 0030) | S0, S22 |
| POST | `/projects/{pid}/benchmark?force=` → `{job_id}`: measure this computer in the project's queue (ADR 0030) | S8, S22 |
| GET/POST | `/admin/media-roots` (server only; `{id, label, path, source: admin\|env}`; POST `{path, label?}` → 201, 422 for a relative or missing folder; ADR 0035) · DELETE `/admin/media-roots/{id}` | S22 (admin) |
| GET | `/fs/browse?root=&path=&cursor=` (server only; without `root`: the roots, no paths. With it: `{root, path, crumbs, here, here: {counts, has_project}, items: [{name, path, counts: {videos, photos, folders, complete}|null, has_project}], next_cursor}`; counts are recursive, capped at 20,000 entries per folder, and `null` once the 2 s listing budget is spent; paths relative to the root; 403 outside it, 404 unknown; ADR 0035, 0039) | S4 |
| GET | `/health` → `{ok}` (public: no sign-in, no host check; the container healthcheck; ADR 0055) | — |

## Settings & secrets

| Method | Path | Used by |
|---|---|---|
| GET/PATCH | `/settings` (returns `{key: {value, source}}` with source = default/user) | S22 |
| GET/PATCH | `/providers` (capability → provider/model/mode, source default/user/inherited, ADR 0019; PATCH `{task: {provider, model} \| null}`, null resets, ADR 0053) · GET `/providers/options` (providers, tasks they serve, models, presets) | S1, S22 |
| PUT | `/secrets/{ref}` (write-only; returns `{configured, last4, store: keychain\|encrypted_file\|environment\|docker, from_deployment}`; a server needs its master key to save, ADR 0036) | S1, S22 |
| DELETE | `/secrets/{ref}` (removes the key the user entered; a deployment key is used again) | S22 |
| POST | `/secrets/{ref}/validate` | S1, S22 |
| GET | `/models/local` · POST `/models/local/{name}/download` (job) | S1 |

## Local models

| Method | Path | Used by |
|---|---|---|
| GET | `/models/local` → `{items: [{name, label, capability, provider, model, bytes, downloaded_bytes, installed, needed, job: {job_id, state, pct} \| null}]}` (`needed`: the current provider profile uses it; `job`: the running download, or the last one if it failed; ADR 0058) | S1, S22 |
| POST | `/models/local/{name}/download` → 202 `{name, job_id, installed}` (an app-level `models` job; the running one if any; `job_id` null when installed; 404 unknown) | S1, S22 |

## Projects

| Method | Path | Used by |
|---|---|---|
| GET | `/projects` (recents from the control DB only: `{id, name, placement, fs_class, folder: {root, path}, missing: true\|false\|null, last_opened_at, card: {clips, photos, footage_seconds, first_date, last_date, cover: [sample ids], analyzed, latest_edit}, status: {state: scanning\|analyzing\|analyzed\|scanned\|not_analyzed, pct?, job_id?, mode?}}`; `missing: null` while a slow folder is still being checked; ADR 0038) | S3 |
| POST | `/projects/preview` `{path}` (desktop) or `{root, path}` (server) → `{name, fs_class, reason, placement, counts: {videos, photos, folders, complete}, project_id}` (no writes; counts and folders only, nothing probed; ADR 0039) | S4 |
| POST | `/projects` `{path \| root+path, name?, placement?}` → `{id, name, created, placement, scan_job, moving_job?}` (a scan-only job; an existing project is opened, `created: false`). When the folder can't hold a live database (`MOSAIC_FOLDER_DB=never` or a host share such as `virtiofs`), a trip made in-folder elsewhere is registered and moved by a `move` job: `{created: false, placement: "split", scan_job: null, moving_job}`; no lease is held and no scan runs until it is opened again (ADR 0055) | S4 |
| POST | `/projects/{pid}/open` `{read_only?, take_over?}` (acquires the lease; `409` `{detail, holder: {host, since, until}}` if open elsewhere; ADR 0023; a trip that must move out of its folder returns `{project_id, moving_job, read_only}` and the move job starts, ADR 0055) · `/close` (releases it) | S0, S3 |
| — | Any `/projects/{pid}/…` route of a trip that still has to move out of its folder → `409` `{detail}` until its `move` job ends; a refused placement → `422` (ADR 0055) | S0 |
| POST | `/projects/{pid}/relink` `{choose_folder?}` (desktop) or `{root, path}` (server; 403 outside the root, 404 refused; 422 if both forms are sent) → `{job_id, root, mode}` (re-scan with the last analysis mode; `409` if the folder is gone and none is chosen; `422` if the chosen folder is not this project's) | S0 |
| GET | `/projects/{pid}/inventory` → `{summary, cameras: [{key, label, kind, device_id, clips, photos, limited, files, footage_seconds, badges, sample_id, clock}], days: [{date, n, clips, by_camera}] (`n`: the trip day as editing and deepening number it), attention: [{kind: unreadable\|limited\|cloud, count, reason, fix, bytes?, group?, example?}], notes: {chaptered_recordings, live_photos, bursts}}` (catalog reasons only) | S5 |
| GET | `/projects/{pid}/inventory/files?kind=unreadable\|limited\|cloud&group=&after=` → `{items: [{id, path, bytes}], next_after}` (S5 "Show files": paths relative to the project folder, 200 per page; `group` from an unreadable row; 404 unknown group; ADR 0040) | S5 |
| POST | `/projects/{pid}/cloud-files/download` → `{job_id}` (reads cloud-only files so the OS downloads them, then rescans) | S5 |
| GET/PUT | `/projects/{pid}/devices` (clock offsets, LUT path; PUT `{devices: [{id, clock_offset_ms \| accept_suggestion \| lut_path \| clear_lut}]}` → `{devices, assets_updated, refresh_job, reanalysis_needed}`; LUTs ADR 0028) · GET `/projects/{pid}/devices/suggestions` (offset, verdict, evidence pairs with `device_sample` and `reference_sample` frame ids; suggestions need the analysis's embeddings; ADR 0027, 0040) | S6, S21 |
| GET/PUT | `/projects/{pid}/trip-context` (PUT returns `summaries_job`: a context change re-runs summaries only) · POST `/trip-context/parse` `{text}` → `{job_id}`; the job's `result.proposal` (`GET /jobs/{id}`) is the proposed structure, saved only by a PUT (ADR 0040) | S7 |
| GET | `/projects/{pid}/summaries?level=day\|trip\|scene\|shot&after_ref=&limit=` (`day`: the trip plus each day; scene and shot are paged by ref, limit ≤ 1000) → `{items: [{level, ref, text, themes?, highlights, subjects?, span?}], next_after_ref}` (ADR 0021) | S10, S16 |
| GET/PATCH | `/projects/{pid}/settings?mode=` → `{settings: {key: {value, source}}}`, source `project` / `user` / `default` / `mode` (an analysis parameter the mode decides; `mode=` shows a preset's values). Keys: `analysis.mode`, `analysis.cost_limit_usd`, `ai.send_gps`, `analysis.sample_interval`, `analysis.tiles`, `analysis.forced_max_shot`, `analysis.proxy`, `analysis.stt_model`. PATCH `{values: {key: value \| null}}` (null resets; 422 invalid; ADR 0041) | S8, S21 |
| DELETE | `/projects/{pid}/recent` → 204 (hides the project from recents and releases its lease; nothing is deleted; opening the folder again brings it back; ADR 0039) | S3 |
| PATCH | `/projects/{pid}` `{name}` (renames the project, not the folder; ADR 0052) | S0, S21 |
| GET | `/projects/{pid}/storage` (groups, regenerable or kept) · POST `/projects/{pid}/storage/clear-cache` (job) · DELETE `/projects/{pid}/workspace` `{confirm_name}` (removes MosAic data; originals untouched; ADR 0051) | S21 |

## Analysis & jobs

| Method | Path | Used by |
|---|---|---|
| GET | `/projects/{pid}/analysis/estimate?mode=&scope=&overrides=` (a preset includes the project's Advanced overrides; `overrides` = JSON of `analysis.*` keys estimates unsaved S8 edits, whole-project only; scope: `trip`, `days:2,3` or `selection:ID,…`; omitted = whole-project run). Returns videos, photos, footage seconds, segments, `l2_calls`, `l3_calls` [lo, hi], `cost_usd` [lo, hi] or null when a model has no price, `storage_bytes`, `wall_seconds` [lo, hi], `basis` (`benchmark` or `default`, ADR 0030), `days` (ADR 0020) | S8, S25 |
| POST | `/projects/{pid}/analysis-runs` `{mode, scope?, overrides?, cost_limit}`; scope `{kind: trip\|days\|selection, days?, segment_ids?}` deepens (mode `balanced` or `thorough`: adds L2 where missing, then L3) and returns `{job_id \| null, candidates, l2_assets, dropped}`; without scope the whole project is analyzed in the mode: a preset with the project's stored Advanced overrides runs as Custom based on that preset (`overrides` only with `custom`, optionally with `base`; ADR 0041) | S8, S25 |
| GET | `/projects/{pid}/analysis/progress?job=` → `{job_id, kind, mode, deepen: {target, days, segment_ids} \| null, steps: [{key, label, state, done, failed, total, pct, note}], ready_to_browse, live: {mosaic_id, tiles, cols, rows, description, file, day} \| null, failures: {count, items: [{asset_id, file, stage, reason}]}, clips: {done, total}}` (latest analysis or deepening job without `job`; reasons are short phrases, never tool output; ADR 0041) | S9 |
| GET | `/jobs?project=&active=` · `/jobs/{id}` (stages, current item, live sample, `cost_usd`, `cost_limit_usd`). Kinds include `move` (one `project.move` task: an in-folder trip's database and cache move to app data; S0 waits on it; ADR 0055) | S9, S0 |
| POST | `/jobs/{id}/pause` · `/resume` (optional body `{cost_limit_usd}`: raise the AI cost limit of a job paused at it; must exceed what the job has spent; ADR 0018) · `/cancel` · `/retry-failed` | S9, S20 |
| POST | `/jobs/pause-all` → `{paused: [id]}` (every waiting or running job) · `/jobs/resume-all` → `{resumed: [id]}` (jobs paused by hand; not those at their cost limit) — the desktop menu bar (ADR 0060) | S0 |
| GET | `/events?project=` (SSE; without `project`: every project, for the rail's activity ring) | all |

SSE event types:

| Event | Payload |
|---|---|
| `job.progress` | `{job_id, project_id, kind, state, pct, stage, item, cost}` |
| `job.stage` | Stage transition |
| `job.state` | running / paused / paused_cost_limit / done / failed / cancelled |
| `analysis.ready_to_browse` | `{job_id, project_id}`, once per analysis job and stream, when L0 and every per-asset L1 task are finished and one succeeded (L2 may still run; a reconnect may repeat it, so dedupe by `job_id`; ADR 0041) |
| `clip.updated` | `{project_id, asset_id, fields}` after a decision change; `asset_id: null` when more than 200 clips changed at once (refetch; ADR 0042) |
| `edit.progress` | `{edit_id, step, beats_planned[]}` |
| `edit.version_created` | — |
| `render.progress` | — |
| `lock.lost` | — |

## Library

| Method | Path | Used by |
|---|---|---|
| GET | `/projects/{pid}/library?group=day\|camera\|similar&cursor=&limit≤200&status=USE\|MAYBE\|REJECT\|none&min_stars=&camera=&day=&tag=&include=always\|never&kind=video\|photo&shot_type=&has_speech=&show_rejected=` → `{items, next_cursor, groups, rejected_hidden}` with keyset pages (ADR 0031, 0042). Items: asset, kind, status, name, group, capture time, duration `{ticks, tb}`, segments, disposition counts, `status_shown` (the tile chip: the best of the clip's segments, each by its own user decision, then the clip's, then the analysis), `decided_by` (`user` \| `ai`), `decision` (`{disposition, stars, include, note, live_motion, tags}`), tile `sample_id`, `caption` and `shot_type` (the AI's words for the clip's most interesting moment), `has_speech`, `similar_count`, `offline` (a file is only in the cloud, or missing: an unplugged drive), `camera` `{label, kind: phone\|actioncam\|360\|drone\|camera\|photo}`. Groups: `{key, label, count, clips, photos, footage_seconds}`; day groups add `day`, `date` and the trip context's `place`; `similar` groups clips by their first similarity group, clips without one last (ADR 0044). Clips shown as REJECT are hidden unless `show_rejected` or `status=REJECT`; `rejected_hidden` counts them. `groups` and `rejected_hidden` on the first page; filters narrow every count; day labels keep the trip's numbering. Density is a client choice | S10 |
| GET | `/projects/{pid}/clips/{aid}?show_rejected=` → `{asset_id, kind, status, name, files, reason, fix, camera, capture_time, duration {ticks, tb}, rate, proxy_rate (the served proxy's frame rate, null until it exists), width, height, badges, analysis_only, position {day, date, index, count, prev, next} \| null, status_shown, decided_by, ai_status, decision, why {description, reasons}, moments [{segment_id, start, end, usable_start, usable_end, status, decided_by: user\|clip\|ai, ai_status, description, interest, reasons, has_speech, sample_id}], quality {sharpness, steadiness, exposure, audio: Poor\|Fair\|Good\|Excellent\|null}, transcript {segments, language}, used_in [{edit_id, name, version}], similar [{asset_id, sample_id}], burst {items [{asset_id, sample_id, best}]} \| null}`; times exact; 404 unknown (ADR 0043) | S11 |
| GET | `/projects/{pid}/clips/{aid}/transcript?after=` → `{items: [{id, start, end, text, language, words: [{start, end, word}]}], next_after}` (200 sentences a page; no speaker names, ADR 0043) | S11 |
| PATCH | `/projects/{pid}/clips/{aid}/decision` `{disposition?: USE\|MAYBE\|REJECT, stars?: 1–5, include?: always\|never, note?, live_motion?, tags?, add_tags?, remove_tags?}`: a field set to null resets it, a field left out is unchanged → `{asset_id, changed, disposition, stars, include, note, live_motion, tags}` (hard constraints for editing: never = REJECT; always / USE keep the clip and force its best moment; a decision on one segment wins; ADR 0042) | S10, S11 |
| POST | `/projects/{pid}/decisions/bulk` `{asset_ids[] ≤ 10,000, …the same fields}` → `{updated}` | S10 |
| GET | `/projects/{pid}/search?q=&mode=all\|visual\|speech&limit=` (items: segment, asset, exact start/end, sample, `status` (the decision in force, null when not analysed), `decided_by` (`user` \| `ai`; ADR 0042), `ai_status`, score, `matched` reasons, the clip's `name` (the file's name; the library's `name` is its path in the folder), `kind`, `camera {label, kind}`, `stars`, `has_speech`; `visual: ok\|unavailable\|off` drives S12's "analysis incomplete" banner) · `/search/suggestions` (the trip's own tags) (ADR 0029) | S12 |
| GET | `/projects/{pid}/labeling-questions` · POST `/labeling-questions/{qid}/answer` | S24 |
| GET | `/media/{pid}/proxy/{aid}` (HTTP range; 404 until a proxy exists) · `/media/{pid}/frame/{sample_id}` (JPEG) · `/media/{pid}/mosaic/{mosaic_id}` (the labelled contact sheet, JPEG; S9) · `/media/{pid}/waveform/{aid}` (`{silent, bucket: {ticks, tb}, count, peaks: base64 0–255}`, from the `media.waveform` stage) · `/media/{pid}/filmstrip/{aid}?n=&start_ticks=&end_ticks=` (`{tb, frames: [{sample_id, ticks}]}`) (ADR 0037) | all |

## Edits

| Method | Path | Used by |
|---|---|---|
| GET/POST | `/projects/{pid}/edits` (GET: S13 cards with status, cover, versions, preliminary; ADR 0047) | S13, S14 |
| GET | `/projects/{pid}/presets` (16 story presets, 7 featured) · `/projects/{pid}/presets/{id}/collage` → `{frames: [sample_id]}` (ADR 0047) | S14 |
| POST | `/edits/estimate` `{project_id, request}` (time, cost, plan reuse, enough footage; ADR 0047) | S14 |
| POST | `/edits/{eid}/generate` (job; emits `edit.progress`) | S14, S15 |
| GET | `/edits/{eid}` (current draft, beats, events, facts) · `/edits/{eid}/versions/{v}` — both with `facts` and the version's `renders` (ADR 0049) | S16, S17 |
| POST | `/edits/{eid}/draft/ops` `{op}` (reorder, lock, replace, remove, trim, faster/slower) · `/draft/undo` · `/draft/redo` | S16 |
| POST | `/edits/{eid}/versions` (commit draft) · GET `/edits/{eid}/versions` · `/versions/{v}` | S16, S18 |
| GET | `/edits/{eid}/compare?a=&b=` (change list) | S18 |
| POST | `/edits/{eid}/beats/{bid}/regenerate` · `/edits/{eid}/regenerate?scope=story\|all` | S16 |
| GET | `/edits/{eid}/shots/{evt}/alternatives` | S16 |
| GET | `/edits/{eid}/findings` · POST `/findings/{fid}/apply` · `/ignore` · `/findings/apply-all` (the AI critic; M4, not in M2) | S17 |
| POST | `/edits/{eid}/preview` (render job) | S16, S17 |
| POST | `/edits/{eid}/revert` `{version}` | S18 |
| GET | `/edits/{eid}/report?version=&rejected_offset=` (selection/rejection report and metrics; rejected list follows ADR 0042, clip-level included) | S17, CLI `mosaic report` |

## Renders

| Method | Path | Used by |
|---|---|---|
| POST | `/renders` `{edit_id, version, preset, resolution, fps, loudness, include[], dest}` | S19 |
| GET | `/projects/{pid}/renders` · POST `/projects/{pid}/renders/{rid}/cancel` · `/rerender` · DELETE `/projects/{pid}/renders/{rid}/file` (render ids are per project; ADR 0047) | S20 |
| GET | `/projects/{pid}/renders/{rid}/file` (Range; `?download=true`) | S17, S20 |
| POST | `/projects/{pid}/renders/{rid}/reveal` (desktop only; not in M2) | S20 |

## Diagnostics

| Method | Path | Used by |
|---|---|---|
| GET | `/diagnostics/tasks?project=&status=&cursor=` · `/diagnostics/tasks/{tid}` | S23 |
| POST | `/diagnostics/tasks/{tid}/retry` · `/skip` (ADR 0051) | S23 |
| POST | `/diagnostics/bundle` (redacted zip; ADR 0051) | S23 |
