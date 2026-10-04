# Analysis Modes

Analysis depth is chosen per project (default from user preferences) and can be **deepened later without redoing earlier work**.

## 1. Levels

| Level | Contents | Cost profile |
|---|---|---|
| **L0 Inventory** | Probe, grouping, sidecars, telemetry, clock suggestions, thumbnails | Seconds to minutes; local |
| **L1 Deterministic** | Proxies, shots, samples, tech metrics, VAD + transcription, embeddings, segments, similarity (embedding-only) | Local CPU/GPU; scales with footage length |
| **L2 Vision tagging** | Mosaic analysis of all segments with an economical vision model; dispositions; summaries | Cloud or local AI; main per-hour cost |
| **L3 Deep review** | High-resolution per-segment re-analysis of **candidates only** (USE/MAYBE, top-ranked per similarity group, user-starred) with a stronger model; moment detection | AI; bounded by the candidate count |

Artifacts are keyed per level and density, so moving Quick → Thorough reuses L0/L1 and only adds what is missing.

## 2. Presets

| Setting | Quick | Balanced (default) | Thorough |
|---|---|---|---|
| Levels | L0, L1 (reduced), L2 | L0–L2 | L0–L3 |
| Proxies | Camera LRF/LRV if valid, else 540p | 720p | 720p |
| Fixed sample interval | 6 s | 3 s | 1.5 s |
| Scene detection | Fast threshold detector | Adaptive detector; shots over 60 s split (ADR 0008) | Adaptive + forced subdivision of long shots |
| Tiles per mosaic | 24 (small tiles) | 16 | 9–12, plus L3 single frames |
| Transcription | Small model, speech segments only | Medium model | Large model, word timestamps everywhere |
| Shake metric | Telemetry only; else skipped | Telemetry or sparse optical flow | Dense optical flow |
| Vision model tier | Economy | Economy | Economy (L2) + Strong (L3) |
| Goal | "Show me something fast" | Solid edits | Best selection and cut points |

**Custom** exposes every parameter (Advanced mode).

For reference, a 4-hour trip at Balanced produces roughly 4,800 samples before deduplication and 150–250 mosaics. Estimates shown to the user must be computed from the actual probe, not taken from this example.

## 3. Progressive deepening

- **Early edits:** after L0 + L1 finish for all assets, the user may start an edit immediately. It is marked "preliminary", with selection based on metrics, transcripts and embeddings only. L2 continues in the background.
- **Deepen analysis** is a one-click action on the project, a day, or a selection. For example, Thorough can be run on just the days that matter.
- **Before an edit on Balanced**, the editing pipeline may request targeted L3 on its shortlisted candidates. This is capped by the edit's cost budget and shown in the edit estimate.

## 4. Estimates and budgets

- Before starting, show:
  - estimated wall time (from a hardware benchmark plus footage duration)
  - storage for proxies and cache
  - AI cost range (from the adapter cost table and the planned mosaic and token counts)
- Cost ceilings are set per project and per edit. When a ceiling is reached, AI tasks pause with a clear prompt; nothing fails silently.
- Actual cost and tokens are recorded in `usage_record` and in provenance.
