# S10 — Library

- **Reference:** `docs/ui/reference/` → S10-Library, S10b-LibraryBulk, S10c-LibraryPrelim, S10d-LibraryLight
- **Milestone:** M2

**Purpose.** The main workspace: browse, search and steer the AI by deciding on clips.

## Layout

`LibraryToolbar`, then a `VirtualGrid` grouped by day (default) with `GroupHeader`s, plus the `DayScrubber` on the right edge.

`ClipInspector` on the right when a clip is selected.

Optional "Help me label" banner (S24) after analysis completes.

Keyboard hint strip at the bottom-left.

## States

- Default (comfortable, inspector open).
- Compact density.
- Multi-select with `BulkBar` (USE / MAYBE / REJECT / Rate / Tag / Always / Never / clear).
- Preliminary: info banner, tiles without analysis show no disposition chip.
- Rejected hidden by default; a "Show rejected (n)" toggle shows them dimmed.
- Empty filter result: "No clips match. Clear filters."
- Offline sources: overlay on the tile, but the proxy still plays.
- Light theme.

## Data & API

- `/library`, `/clips/{aid}`, `PATCH /decision`, `/decisions/bulk`, `/media/...`, SSE `clip.updated`.

## Keyboard

- ←/→/↑/↓ move · Space play · Enter open full view · 1–5 stars · 0 clear stars · U/M/R disposition · L always include · X never include · Shift-click range · ⌘-click toggle · ⌘A select all in group · / search · Esc clear selection.

## Acceptance

- A user decision renders as user style immediately (optimistic) and persists.
- 5,000 items scroll smoothly with ≤ 60 tiles mounted.
- Hover-scrub uses sample frames, not video decode.
