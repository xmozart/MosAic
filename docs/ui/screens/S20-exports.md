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

## M2 notes (ADR 0050)

- The route is `/p/:pid/exports`; `/exports` opens the newest trip's.
- Done rows offer Open, Download and Delete (with a confirmation). Show in Finder waits for the desktop app.
- Failed rows show "Stopped at n %", Details (the error) and Re-render.

