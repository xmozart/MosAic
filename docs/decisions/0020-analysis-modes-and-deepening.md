# ADR 0020 — Analysis modes, camera proxies and deepening

- **Status:** accepted (agent decision, M1 step 4)
- **Date:** 2026-10-05

## Context

ANALYSIS_MODES.md defines Quick, Balanced, Thorough and Custom, and says that deepening a
scope reuses earlier work. M1 acceptance 5 is stricter: going Quick → Thorough on one day
re-uses all L0/L1 artifacts, and the new AI calls equal that day's L3 candidates. Several
details were left open:

- how a mode reaches each stage;
- what "reduced L1" means for Quick;
- how a camera LRF can replace the 540p transcode without breaking invariant 4;
- how a whole-project run differs from deepening;
- what an estimate can know before analysis.

## Options

1. One parameter set per project. Switching mode would recompute everything.
2. **Every job carries its mode** (chosen). Each stage puts the parameters that change its
   output into its artifact key. Deepening is a separate job kind that only adds levels.

## Decision

- **A mode is a `ModeConfig`** (`core/modes.py`):
  - proxy (`720` or `lrf_or_540`), sample interval, detector (adaptive or threshold),
    forced split length, tiles per sheet, Whisper model, L2 and L3 flags;
  - stored in the job's params (`mode_config`). Jobs from before modes read as Balanced;
  - Custom is Balanced plus explicit overrides. Unknown parameters are rejected.
- **Custom is validated.** The Whisper model must be one with a pinned revision
  (`small`, `medium`, `large-v3`). L3 requires L2, because it reviews the candidates L2
  produces.
- **Rows follow the last run.**
  - The `visual` and `audio` stages replace an asset's rows (shots, samples, metrics,
    transcripts) on every run. So an existing artifact does not prove those rows are its
    own: after Balanced → Quick → Balanced, the Balanced artifact exists, but the rows are
    Quick's.
  - `asset_stage` (asset, stage) records the key that wrote the current rows. It is set
    to empty when a run starts and to the key when the run finishes. A stage is done only
    when its artifact exists *and* the recorded key matches.
  - Projects from before M1 have no record. They were analyzed in Balanced only, so the
    existing artifact is trusted. An integration test switches Quick → Thorough → Quick.
- **Balanced keys are unchanged from M0.** The proxy key gains `source` only for camera
  proxies; the visual key is the M0 `CONFIG` for Balanced; the Whisper model is unchanged
  when the mode does not name one. Existing analyses stay valid, and a unit test pins this.
- **Quick proxies.**
  - When every chapter has a *valid* LRF/LRV sidecar (same frame rate, and video duration
    within two frames: `profiles.lrf_matches`), the camera's proxy is transcoded instead of
    the original: 540p cap, 2 Mb/s, the sidecar's own streams.
  - The camera proxy is frame-aligned with the original, so the plan keeps the
    *original's* logical chapter spans, and the tick map stays in the original's ticks
    (invariant 4).
  - An integration test reads the barcode of every frame of the Quick proxy and checks it
    against the original's frames.
  - A camera proxy without sound, when the original has sound, is not used:
    transcription needs the sound.
  - Without camera proxies, the originals are transcoded at 540p.
  - The proxy of a different mode is a different artifact. Callers outside a job
    (previews, the renderer's fallback) take whichever proxy exists, preferring 720p.
- **Stages have levels.** `mosaics` and `vision` are L2; `deep review` (a project stage
  after dispositions) is L3. Rule dispositions run in every mode. `plan_stages` drops the
  levels a mode excludes. Thorough's L3 stage spawns one review task per asset plus a
  second dispositions task, which merges the reviews.
- **Two kinds of run** (`POST /analysis-runs`):
  - *Without a scope*, the whole project is analyzed in the mode. A stage recomputes only
    when its key differs, so switching to a denser mode recomputes L1 at the new density.
    That is what a whole-project mode change asks for.
  - *With a scope* (the trip, some days, or a selection), the run **deepens**. Its target
    is Balanced or Thorough. It adds L2 for clips that have none (no contact sheets, or
    sheets without observations), then, for Thorough, L3 on the candidates. It never runs
    an L0/L1 stage.
  - Acceptance 5 is the scoped path. The test asserts that the L0/L1 artifact set is
    identical before and after, and that the only new AI calls are one review per
    candidate.
  - Overrides apply only to whole-project runs.
- **Estimates** are computed from the probed inventory, and from the library when it has
  data: the real mean segment length, the real candidate count, and existing reviews.
  - Unknowns are ranges: the segment count before analysis, and the L3 candidate share
    (30–60 %).
  - Cost uses each provider's keyless price table (`ProviderEntry.price`): subscription
    apps cost $0; a model without a price, or a provider registered without a price
    table, gives an unknown cost, not a guess.
  - Wall time uses per-mode speed factors from the M0 eval until the hardware benchmark
    (step 12) replaces them.
  - An estimate needs the inventory (L0). The S8 flow reaches it after S5, which shows
    the inventory.
- **Not varied by mode yet:**
  - the shake metric (ANALYSIS_MODES lists telemetry-only, sparse and dense optical flow);
  - Quick's "speech segments only" transcription;
  - Thorough's "word timestamps everywhere". Every mode already transcribes with word
    timestamps inside VAD speech.

  These parameters are not part of `ModeConfig`. Adding one later changes only that
  stage's key for the modes that set it.

## Consequences

- The UI (S8, S25, M2) has the API it needs: per-mode estimates, scoped deepening with a
  target, and Custom overrides.
- Thorough downloads Whisper large-v3 on first use (MIT, pinned revision). Tests pin
  `small` through `MOSAIC_STT_MODEL`.
- `mosaic deepen` takes repeatable `--day` and a `--target`. `mosaic analyze` takes
  `--mode`, `--set KEY=VALUE` (Custom) and `--estimate`.
