# ADR 0007 — Proxies are capped at 30 fps; one proxy per asset

- **Status:** accepted (agent decision, M0 step 5)
- **Date:** 2026-10-04

## Context

`ARCHITECTURE.md §8` asks for 720p H.264 8-bit SDR Rec.709 CFR proxies that serve both
analysis and browser playback, but does not fix their frame rate. The real corpus is
4K 59.94 (Dubai GoPro) and 4K 29.97 (Airshow, about 90 minutes); iPhone slo-mo can be
120–240 fps. Shot detection, sampling and motion metrics run on the proxy, so its frame
count drives L1 cost.

## Options

1. Proxy at the source rate.
2. Proxy at a fixed 30 fps.
3. Source rate halved until it is at most 30 fps (59.94 → 29.97, 50 → 25, 120 → 30).

## Decision

Option 3. Halving keeps the rate an exact divisor of the source, so every proxy frame is
one source frame (no blending). For verified CFR sources the tick map is affine (proxy
frame `i` is logical source time `i / proxy_rate`); VFR or unverified sources store a table
of the source frame PTS each proxy frame shows (ARCHITECTURE.md §6). One proxy covers an asset's whole logical timeline; GoPro
chapters are concatenated.

## Consequences

- L1 work on 60 fps sources halves; motion metrics see 30 fps, enough for shake and
  camera-motion estimates.
- Preview renders (from proxies) of 59.94 fps timelines repeat proxy frames; final renders
  use the originals and are unaffected.
- `ARCHITECTURE.md §8` stage 3 is updated.
