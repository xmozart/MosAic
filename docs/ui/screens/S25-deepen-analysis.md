# S25 — Deepen Analysis

- **Reference:** `docs/ui/reference/` → S25-Deepen
- **Milestone:** M2

**Purpose.** Run deeper analysis on part of the trip.

## Layout

560 px dialog with:

- scope (Whole trip / Selected days / Current selection)
- day checklist with clip counts
- target (Balanced / Thorough)
- estimate card
- Start

## States

- Estimate loading.
- Nothing selected (Start disabled).

## Data & API

- `/analysis/estimate?scope=`, `POST /analysis-runs`.

## Acceptance

- Reuses existing artifacts; AI calls equal the new L3 candidates only.
