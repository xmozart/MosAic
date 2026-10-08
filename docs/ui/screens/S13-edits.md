# S13 — Edits

- **Reference:** `docs/ui/reference/` → S13-Edits
- **Milestone:** M2 basic, M4 full

**Purpose.** All edits for this project.

## Layout

Header with a large Create edit button. A 4-column grid of `EditCard`s. Vertical edits show a 9:16 cover centered in the frame.

"Start from" chips: duplicate as another length, vertical version, saved preset.

## States

- Empty: "Create your first edit".
- Generating (ring over the cover).
- Preliminary (warning: "Made before analysis finished — regenerate for better results").
- Final rendered / Preview ready.

## Data & API

- `/projects/{pid}/edits`, `/presets`.

## M2 notes (ADR 0048)

- Status words, polling and the "Start from" chips (duplicate as another length, vertical version) are in ADR 0048. "Saved preset" waits for M4.
- A card opens S17 (`/p/:pid/edits/:eid`).
