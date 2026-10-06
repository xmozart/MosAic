# 0031 — The 40-hour scale test and the library list API

- Status: accepted (M1 step 13)
- Deciders: agent (autonomous; no human gate)

## Context

M1 acceptance 6 reads: "The 40-hour synthetic project completes L0/L1 with bounded memory (peak RSS limit set in the test) and a UI-API list page response under 300 ms."

EVALUATION.md §1 describes the project as "low-res, generated lazily".

Three things are missing or unsettled:
- **No list endpoint.** The UI list it refers to (S10 Library, `GET /projects/{pid}/library`) belongs to M2's UI and did not exist yet.
- **Runtime.** At real resolution and frame rate, 40 hours of L0/L1 takes about 13 hours on the eval machine (ADR 0030 benchmark), far too long for `make ci`.
- **Embeddings.** SigLIP embeddings at roughly 145 ms per sample would add about 2 hours for 48,000 samples.

## Options

**Footage**
1. Real-resolution 40 hours, run outside `make ci`. This contradicts "acceptance passes in `make ci`".
2. Shorter footage, extrapolated. This is not the acceptance test as written.
3. Forty hours of low-resolution, low-frame-rate clips. Their duration, file count, sample count, segment count and DB rows match a long trip, while decoding costs a small fraction.

**Embedder**
1. Real SigLIP: hours.
2. A content-based fake embedder. It keeps every embedding-dependent stage (vector index, similarity, segments) at full row counts.

**List API**
1. Wait for M2 and test some other list.
2. Build S10's paging core now, `/library` with keyset pages in day or camera order, and leave S10's filters and density options for M2.

## Decision

**Generator** (`devtools/longproject.py`, `mosaic-dev gen-long DIR [--hours]`)
- 400 clips of 6 minutes each, 192×108 at 1 fps (the test's `LongSpec(fps=1)`), H.264.
- Clips are spread over 5 trip days with `creation_time` tags.
- Scene lengths vary from 20 to 89 s.
- Every tenth clip has a tone soundtrack, so the audio stage runs.
- A manifest records the parameters, and a folder that matches them is reused. Clips are written as `.part` files and renamed, so an interrupted generation resumes, but only for the same spec: a partial manifest records it, and clips made for another spec are deleted first.
- The project lives in `.cache/long-40h` (ignored by git; overridable with `MOSAIC_LONG_PROJECT_DIR`). Each run analyzes a hard-linked copy, so the cache stays pristine.

**Fake embedder** (`ai/adapters/fake/embedder.py`)
- Each frame's 4×4 colour layout becomes a 48-dimensional normalized vector; text maps to a hash vector.
- The `fake` provider now also serves `embedder`. It is never a default, and `set_provider all fake` still covers only cloud capabilities.

**The test** (`tests/acceptance/test_m1_scale.py`)
- Runs L0/L1 (Custom mode with `l2=false`).
- **Memory:** the worker runs in its own process and reports its peak RSS on exit, with a limit of 1.5 GB. Measured at 4 hours, the peak was about 0.5 GB and flat; at 40 hours it was 500 MB, the same, so memory does not grow with project length.
- **List speed:** every library page (100 items) in both groupings, after one warm-up request, must answer in under 300 ms.
- The RSS is the worker process alone; FFmpeg children are separate processes with their own bounded buffers.
- It also checks that all 400 assets are ok and that segment and sample counts reach a long trip's scale.
- It writes `.cache/scale-report.json` for the report.

**Library list** (`library/browse.py`, `GET /projects/{pid}/library?group=day|camera&cursor=&limit=`)
- Pages use keyset pagination on (camera,) capture time and asset id, with an opaque cursor. There is no offset scan, so a deep page costs what the first does; each page sorts the shown assets once (one row per clip). An expression index can be added if photo-heavy projects need it.
- Undated clips sort last.
- **Day** is the date in the clip's own corrected time string.
- **Shown:** video, photo and Live Photo assets that are not unsupported.
- **Per item:** name, kind, status, group key, capture time, duration `{ticks, tb}`, segment count, effective disposition counts per segment (a user decision overrides the analysis; `user` counts those) and the tile frame. These come from four batched queries over the page's ids.
- `groups` (key, label, count) comes with the first page only.
- A cursor that doesn't fit the grouping, or is malformed, gets a 422.

## Consequences

- `make ci` grows by roughly 10–15 minutes for this test. The first run also generates about 300 MB of clips (about 3 minutes).
- **What it does not measure:**
  - Real-resolution decoding speed. The hardware benchmark (ADR 0030) covers that.
  - SigLIP time.
  - Whisper on long speech.
  - L2 cost. Its row counts scale with segments, and it is per-mosaic tasks.
- **Threads and speed.** Worker slots are threads in one process (ADR 0002 K). Python-heavy per-frame work in parallel slots contends for the GIL; on the 4-hour run, summed task time was about 5× wall time on 5 CPU slots. Memory stays bounded, so this is a speed matter. It is recorded as a follow-up: process-based CPU slots, considered with the M2 desktop packaging.
- **Day grouping.** It uses the stored offset of the corrected time. Mixed time zones on one trip day can split a day until per-device zones (ADR 0027) feed the label; M2's S10 work refines this.
- **M2 extends this endpoint** with filters (rejected hidden, stars, tags), density, similar-groups and the SSE `clip.updated` contract. The paging contract stays.
- **Measured on the eval machine** (Apple M4, 5 CPU slots):
  - L0/L1 of 40 hours took 922 s, covering 11,297 segments and 49,325 samples.
  - Worker peak RSS was 500 MB.
  - The slowest of 8 library pages took 18.6 ms.
