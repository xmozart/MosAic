# S20 — Exports

- **Reference:** `docs/ui/reference/` → S20-Exports
- **Milestone:** M2

**Purpose.** The render queue and history.

## Layout

Table-like list (the one place a list is fine) with columns: cover, edit and version and preset, status (with progress), size, time, actions.

## States

- Queued.
- Rendering n%.
- Done (Open / Show in Finder or Copy link).
- Failed (Details / Re-render).

## Data & API

- `/projects/{pid}/renders`, `/renders/{rid}/*`.
