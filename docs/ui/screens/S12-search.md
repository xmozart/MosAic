# S12 — Search

- **Reference:** `docs/ui/reference/` → S12-Search
- **Milestone:** M2

**Purpose.** Natural-language search over visuals and speech.

## Layout

The query stays in the screen's search field, and in the URL (`?q=&mode=`).

**Deviations (ADR 0045):** the Library toolbar's filter chips, Group, Density, "Deepen analysis…" and "Create edit" are not on this screen. Header: "n results for …" with segmented All / Visual / Speech and suggestion chips.

Grid of tiles. Under each tile: **matched:** a reason (visual tags or a transcript snippet).

## States

- Results.
- No results (with suggestions).
- Analysis incomplete (info banner).
- Searching (skeleton tiles).

## Data & API

- `/search`, `/search/suggestions`.

## Keyboard

- / focuses search; Enter runs it; Esc clears.

## Acceptance

- Suggestions come from this trip's own tags.
