# Evaluation

An AI editor improves only if changes to prompts, models and algorithms are measured.

## 1. Test media

**Synthetic corpus** (generated in CI with FFmpeg `testsrc2`, `sine` and metadata injection). Each case pins a specific failure mode:

| Case | Purpose |
|---|---|
| VFR clip | Timing and PTS mapping |
| Rotated clip | Display-matrix rotation (90° and 270°) |
| HLG and PQ tagged clips | Color handling and tone mapping |
| Nonzero start_time / edit-list clip | Start-offset handling |
| 2-chapter GoPro-named pair | Chapter grouping |
| No-audio clip | Silence generation |
| Multi-audio-track clip | Audio track selection |
| 120 fps clip | HFR detection |
| Corrupt file | Graceful unsupported handling |
| HEIC + MOV Live Photo pair | Live Photo pairing |
| Portrait JPEG with EXIF orientation | Photo orientation |
| Full-range 8-bit (`yuvj420p`) | Color-range handling |
| 10-bit HEVC at 59.94 | High bit depth and nearest-frame conform |
| PQ-tagged clip | PQ tone mapping |
| GoPro chapter pair with LRF sidecars | Chapter grouping and LRF validation |
| 40-hour synthetic project (low-res, generated lazily) | Scale |

Every synthetic video carries a burned-in, encode-robust **frame-index barcode**. Frame-accuracy tests decode it from rendered output and compare against the EDL (±1 frame; nearest-PTS for VFR). See ADR 0002 E.

**Real corpus** (folder set by the app setting `eval.corpus_dir`, ADR 0003; never committed):
- 3 or more trips from the owner, covering mixed cameras, one short (under 20 min) and one long (over 3 h).
- Each trip includes an `expectations.yaml` listing must-include moments and must-exclude material (accidental recordings, pocket shots). The agent drafts these from analysis with `draft: true`; draft-based metrics are reported but not blocking until the owner confirms them at a G6 gate.
- Current corpus: Airshow (about 90 min, GoPro) and Dubai (about 4 min of video plus photos). A trip over 3 hours is required from M1, using the synthetic long project until a real one is added.

## 2. Deterministic edit metrics (computed for every generated edit)

| Metric | Target |
|---|---|
| Duration error | Within tolerance (100%) |
| Mid-word cuts | 0 |
| Dialogue truncations (sentence cut before its end without intent) | 0 |
| Same similarity group within 5 events | ≤ 1 occurrence per 5 min |
| Adjacent jump cuts (same asset, gap < 2 s) | 0 (from M4, intentional jump cuts can be marked and exempted) |
| Shots with REJECT disposition used (not user-locked) | 0 |
| Shake percentile of used shots | Median above project median |
| Must-include recall (real corpus) | Tracked, trend upward |
| Must-exclude violations (real corpus) | 0 |
| Day/beat coverage vs. request | Reported |

## 3. Human rubric (real corpus, per milestone)

Score each on a 1–5 scale:
- Opening
- Story flow
- Variety
- Pacing
- Cut quality
- Audio
- Ending
- "Would I share this?"

Scores are recorded in `tests/evaluation/results/<milestone>/<trip>.md` along with the model, prompt and config versions.

## 4. Regression harness

- `make eval` runs the pipeline on the real corpus using **cached** L0–L2 artifacts, so it re-runs editing only. It then computes metrics and diffs them against the last baseline.
- **Prompt changes** require an eval run. A regression on any zero-target metric blocks the merge.
- **Determinism:** temperature 0 (or the lowest the provider offers) for selector, solver inputs and critic. Solver and refiner are fully deterministic and unit-tested.
