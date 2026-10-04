# S8 — Analysis Setup

- **Reference:** `docs/ui/reference/` → S8-AnalysisSetup
- **Milestone:** M2

**Purpose.** Choose analysis depth with honest estimates.

## Layout

Three `ModeCard`s (Quick / Balanced (Recommended) / Thorough), each with a mono estimate line.

Info banner: you can start editing early and deepen later.

Collapsible **Advanced** grid: sample interval, frames per sheet, scene sensitivity, preview resolution, speech model, scene-understanding model, story model, processing device, GPS toggle, cost limit.

Footer: Back · estimate summary · Analyze.

## States

- Estimates loading: skeleton lines.
- Local-only mode: cloud model fields show "Not available in Local only".

## Data & API

- `/analysis/estimate`, `POST /analysis-runs`.

## Acceptance

- Estimates are computed from the actual probe (never static).
- Advanced overrides are stored as project settings with source shown.
