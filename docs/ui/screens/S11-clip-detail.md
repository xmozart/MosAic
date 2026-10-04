# S11 — Clip Detail

- **Reference:** `docs/ui/reference/` → S11-ClipDetail, S11b-ClipVariants
- **Milestone:** M2

**Purpose.** Everything about one clip, and the AI's reasoning.

## Layout

Back link, position ("Day 3 · 2 of 44") and prev/next.

**Left:** `Player` with the usable range and moment markers, `Filmstrip`, `Waveform` (selection in accent), `Transcript` card.

**Right column (380 px):**

- title line with badges
- disposition and stars
- AI-vs-you line
- Why, Moments, Quality, Used in edits, Note

## States

- Video with speech.
- Video without speech (the transcript card is hidden).
- Photo: EXIF line, Live Photo motion toggle, burst strip with the best pick outlined.
- Unsupported: reason and export instructions instead of the player.
- 360: forward-view player and the 360 info banner.

## Data & API

- `/clips/{aid}`, `/transcript`, `PATCH /decision`.

## Keyboard

- J/K/L, ←/→ frame step, [ / ] previous/next clip, plus the Library decision keys.

## Acceptance

- Clicking a transcript word seeks within 1 frame.
