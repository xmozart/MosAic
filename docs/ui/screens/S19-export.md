# S19 — Export

- **Reference:** `docs/ui/reference/` → S19-Export
- **Milestone:** M4

**Purpose.** Render the final video and sidecar outputs.

## Layout

900 px dialog with:

- presets: Web H.264 / High quality HEVC / Master ProRes, each with size and time estimates
- resolution, frame rate, loudness
- Also include: SRT, selection report, JSON; the NLE timeline option is disabled and labelled "Coming later"
- Save to
- footer: encoder note, Cancel / Render

## States

- Encoder unavailable for a preset (disabled, with a reason).
- Destination not writable.

## Data & API

- `POST /renders`, `/system/info` (encoders).

## Acceptance

- Renders always conform from the originals.
