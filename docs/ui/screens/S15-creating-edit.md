# S15 — Creating Edit

- **Reference:** `docs/ui/reference/` → S15-Creating
- **Milestone:** M4

**Purpose.** A focused interstitial while the edit is generated.

## Layout

**Left:** title, step list (Finding candidates → Planning → Choosing shots → Fitting to target → Refining cuts → Checking → Rendering preview), Run in background / Cancel.

**Right:** beats appear as they are planned, with thumbnails. The beat in progress is highlighted; future beats are dimmed.

## States

- Running.
- Cancelled.
- Failed (with retry and the reason in plain language).

## Data & API

- SSE `edit.progress`, `/jobs/{id}/cancel`.

## Acceptance

- Moving to the background keeps progress visible in the activity ring and on the edit card.
