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
| POST | `/auth/setup` · `/auth/login` · `/auth/logout` | S2 |
| GET | `/system/info` (mode: desktop/server, version, hardware probe with fingerprint, encoders, `workers` slots per resource class, `benchmark` or null, `rate_limits` per provider; ADR 0030) | S0, S22 |
| POST | `/projects/{pid}/benchmark?force=` → `{job_id}`: measure this computer in the project's queue (ADR 0030) | S8, S22 |
| GET/POST/DELETE | `/admin/media-roots` | S22 (admin) |
| GET | `/fs/browse?root=&path=` (server only; within media roots; returns counts and has_project) | S4 |

## Settings & secrets

| Method | Path | Used by |
|---|---|---|
| GET/PATCH | `/settings` (returns `{key: {value, source}}` with source = default/user) | S22 |
| GET/PATCH | `/providers` (capability → provider/model/mode, source default/user/inherited, ADR 0019) | S1, S22 |
| PUT | `/secrets/{ref}` (write-only; returns `{configured, last4}`) | S1, S22 |
| POST | `/secrets/{ref}/validate` | S1, S22 |
| GET | `/models/local` · POST `/models/local/{name}/download` (job) | S1 |

## Projects

| Method | Path | Used by |
|---|---|---|
| GET | `/projects` (recents with cover sample ids, status, placement, missing flag) | S3 |
| POST | `/projects/preview` `{path}` → quick scan counts and placement class (no writes) | S4 |
| POST | `/projects` `{path, name}` → project, plus a scan job | S4 |
| POST | `/projects/{pid}/open` `{read_only?, take_over?}` (acquires the lease; `409` `{detail, holder: {host, since, until}}` if open elsewhere; ADR 0023) · `/close` (releases it) | S0, S3 |
| POST | `/projects/{pid}/relink` `{choose_folder?}` → `{job_id, root, mode}` (re-scan with the last analysis mode; `409` if the folder is gone and none is chosen; `422` if the chosen folder is not this project's) | S0 |
| GET | `/projects/{pid}/inventory` (cameras, day histogram, needs-attention, grouping notes) | S5 |
| POST | `/projects/{pid}/cloud-files/download` (job) | S5 |
| GET/PUT | `/projects/{pid}/devices` (clock offsets, LUT path; PUT `{devices: [{id, clock_offset_ms \| accept_suggestion \| lut_path \| clear_lut}]}` → `{devices, assets_updated, refresh_job, reanalysis_needed}`; LUTs ADR 0028) · GET `/projects/{pid}/devices/suggestions` (offset, verdict, evidence pairs; ADR 0027) | S6, S21 |
| GET/PUT | `/projects/{pid}/trip-context` (PUT returns `summaries_job`: a context change re-runs summaries only) · POST `/trip-context/parse` `{text}` → proposed structure | S7 |
| GET | `/projects/{pid}/summaries?level=day\|trip\|scene\|shot&after_ref=&limit=` (`day`: the trip plus each day; scene and shot are paged by ref, limit ≤ 1000) → `{items: [{level, ref, text, themes?, highlights, subjects?, span?}], next_after_ref}` (ADR 0021) | S10, S16 |
| GET/PATCH | `/projects/{pid}/settings` (effective values with source) | S21 |
| GET | `/projects/{pid}/storage` · POST `/storage/clear-cache` | S21 |
| DELETE | `/projects/{pid}/workspace` (removes MosAic data; originals untouched) | S21 |

## Analysis & jobs

| Method | Path | Used by |
|---|---|---|
| GET | `/projects/{pid}/analysis/estimate?mode=&scope=` (scope: `trip`, `days:2,3` or `selection:ID,…`; omitted = whole-project run). Returns videos, photos, footage seconds, segments, `l2_calls`, `l3_calls` [lo, hi], `cost_usd` [lo, hi] or null when a model has no price, `storage_bytes`, `wall_seconds` [lo, hi], `basis` (`benchmark` or `default`, ADR 0030), `days` (ADR 0020) | S8, S25 |
| POST | `/projects/{pid}/analysis-runs` `{mode, scope?, overrides?, cost_limit}`; scope `{kind: trip\|days\|selection, days?, segment_ids?}` deepens (mode `balanced` or `thorough`: adds L2 where missing, then L3) and returns `{job_id \| null, candidates, l2_assets, dropped}`; without scope the whole project is analyzed in the mode (`overrides` only with `custom`) | S8, S25 |
| GET | `/jobs?project=&active=` · `/jobs/{id}` (stages, current item, live sample, cost) | S9, S0 |
| POST | `/jobs/{id}/pause` · `/resume` (optional body `{cost_limit_usd}`: raise the AI cost limit of a job paused at it; must exceed what the job has spent; ADR 0018) · `/cancel` · `/retry-failed` | S9, S20 |
| GET | `/events?project=` (SSE) | all |

SSE event types:

| Event | Payload |
|---|---|
| `job.progress` | `{job_id, pct, stage, item, cost}` |
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
| GET | `/media/{pid}/proxy/{aid}` (HTTP range) · `/media/{pid}/frame/{sample_id}` · `/media/{pid}/waveform/{aid}` · `/media/{pid}/filmstrip/{aid}` | all |

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
