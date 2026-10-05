# ADR 0001 — M0 findings: weakest quality areas and the focus for M1–M4

- **Status:** accepted by the owner at gate G6 (2026-10-05): "Context is probably the key here." The owner asks for more aircraft footage (especially the F-35 demo) and fewer crowd shots on Airshow.
- **Date:** 2026-10-05
- **Evidence:**
  - `make eval` on the owner's corpus with Claude Code (`claude-cli`): Haiku 4.5 for
    vision; Sonnet 5.5 requested for the planner and selector.
  - Results in `tests/evaluation/results/M0/`; renders under each trip's
    `MosAic/renders/`.
  - `make ci` on the synthetic corpus.

## What works

- **Exact mechanics on real footage.** Both real edits land exactly on target: Airshow
  3:00 = 5395 frames at 29.97, Dubai 1:15 = 4496 frames at 59.94. Every blocking
  metric is zero:
  - mid-word cuts
  - dialogue truncations
  - adjacent jump cuts
  - REJECT shots used

  Loudness is −14.2 / −13.9 LUFS with true peak −1.4 dBTP. The HLG/Dolby Vision iPhone
  clip in Dubai is tone-mapped correctly.
- **Story structure.** The planner writes sensible beats from vision descriptions alone.
  Airshow: skywriting opening → waterfront → visitors → dock life → aboard the boat →
  air show over the water → calm horizon.
- **Cost and time.**
  - The whole eval cost $0 of API budget (subscription provider).
  - Airshow (90 min, 4K30) analyzed in about 27 min; Dubai in 2.5 min. Editing takes
    under a minute and the final render about 2 min.
  - Re-runs reuse everything cached.

## Weakest areas (ranked)

1. **Vision judgement without trip context.**
   - Haiku called sky shots with a distant aircraft "not usable" ("blue sky with a tiny
     dark speck"). In the first run 105 of 485 Airshow segments were flagged "not usable".
     27 of them were REJECT for that reason alone and are now MAYBE (REJECT 119 → 92).
   - Bare "not usable" is now MAYBE (ADR 0013 amendment), but the underlying problem
     remains: the model does not know what the trip is about.
   - Some sideways or tilted horizons and shots dominated by another spectator's lens
     were still selected.
2. **Must-include recall is low on Airshow (1/8 of the draft moments).**
   - Only 1 of the 8 drafted "high interest, good composition" moments made the 3-minute
     edit. They cluster in two recordings, and the selector spreads across the day.
   - The drafts are unconfirmed, so this blocks nothing, but it shows the selector does
     not prioritise the strongest moments.
3. **Endings and openings.**
   - Dubai ends on a person in a VR headset indoors, which is not a "calm, memorable"
     closer.
   - Airshow opens on a sun-flare shot with a telephoto lens in frame.
   - The critic does not judge story quality yet; the AI critic is M2+.
4. **Similarity on real footage.** About 40–45 % of segments are marked near-duplicates
   (215 of 485), because `MAX_DISTANCE` is tuned only on synthetic frames. The retrieval
   fallback hides this on short trips; on long trips it could drop good alternatives.
5. **Thresholds are uncalibrated.** The disposition thresholds (black / obstructed /
   shake / blur) and `VISUAL_CHANGE` are first estimates. GX010346 has 66 of 124
   segments rejected by rule and AI together; this needs owner review.
6. **Provenance detail.** The Claude CLI also reports the helper models it used, and the
   eval recorded Haiku as the served model for planner and selector calls that had
   requested Sonnet. The parser is fixed: the requested model wins. These eval rows
   cannot be re-verified after the fact.
7. **Real-footage robustness found only by the eval.** Two bugs appeared only at real
   scale. Both are fixed, with regression tests (builder limits and argv, plus a
   decoded-sample check on the MP4 preview):
   - FFmpeg's expression limit with 120 sample frames per call;
   - an AAC duration check that miscounted priming samples.

## Recommended focus

- **M1 (owner-confirmed priority first):**
  - Trip context (PRODUCT §3) in the planner, selector and summaries, plus an L3
    (Thorough) full-resolution review of aircraft and sky candidates that is aware of the
    context. The root cause is resolution as much as context: in a 392 px tile, a jet is
    a speck.
  - Calibrate `MAX_DISTANCE`, `VISUAL_CHANGE` and the disposition thresholds on Airshow
    and Dubai, using the confirmed expectations.
  - Horizon/tilt detection from gyro (GoPro GPMF) as a MAYBE reason.
  - A >3 h trip.
- **M2:**
  - Review UI for dispositions and expectations (user REJECT/USE as hard constraints is
    already supported).
  - The AI critic for opening and ending strength.
  - Per-beat regeneration.
- **M3–M4:** music-aware pacing; selector prompts that weigh "hero" moments against
  coverage; Thorough-mode L3 single-frame review for top candidates.
- **Process:** keep `make eval` in the loop for every prompt change (EVALUATION §4). Treat
  real-footage-only failures as regression fixtures; add a long, many-sample synthetic
  asset to the corpus.
