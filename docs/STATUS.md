# STATUS

The agent maintains this file. It is the resume point for every new session.

## ⚠ Waiting for owner

_(empty — the agent is working)_

## Current

- **Milestone:** M0
- **Step:** not started. The owner approved the M0 plan; ADR 0002 records the decisions. ADR 0003: AI provider, key and corpus path are app settings the owner enters later via `mosaic config`; don't gate on them before step 12 needs them.

## M0 plan

- [ ] 1. Scaffold, `core/time.py` with property tests, FFmpeg builders and license/capability probe, LGPL FFmpeg build script, synthetic corpus generator with barcodes
- [ ] 2. Storage: control and project DBs, placement classifier, descriptor, artifact store, provenance, `mosaic init`, float-seconds schema test
- [ ] 3. Jobs: DAG, leases, Executor, worker process, resume after kill; FastAPI skeleton with `/api/jobs` and SSE
- [ ] 4. L0: probe, camera profiles, chapters, sidecars, unsupported reasons, deferred photos
- [ ] 5. Proxies: tone mapping, rotation, color range, VFR→CFR, tick map
- [ ] 6. Shots, samples, tech metrics, shake
- [ ] 7. Audio: VAD, Whisper word ticks, loudness, speech fixture
- [ ] 8. Embeddings, segments with usable_range, similarity groups, GPMF if feasible
- [ ] 9. Mosaics, AI interface and provider registry, Anthropic and fake adapters, app configuration and `mosaic config` CLI (ADR 0003), vision v1, budgets, dispositions
- [ ] 10. Editing: retrieval, planner, selector, solver, refiner, critic, versions, `mosaic edit`/`report`
- [ ] 11. Render: chunks, conform, tone mapping, pillarbox, silence, loudnorm, encoder selection
- [ ] 12. Acceptance in `make ci`, `make eval` on the corpus, draft expectations, reports, findings → gate G6

## Log

_(one line per commit: date · step · summary)_
