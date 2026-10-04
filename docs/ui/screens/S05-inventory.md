# S5 — Inventory

- **Reference:** `docs/ui/reference/` → S5-Inventory
- **Milestone:** M2

**Purpose.** Show what was found and surface problems before analysis.

## Layout

Heading "Here's what we found" with a summary strip on the right: footage, clips, photos, dates, cameras.

Camera cards (5 per row): frame, icon and model, counts, badges, clock warning.

Trip timeline: per-day stacked bars by camera, with a legend.

Clock card linking to S6.

**Needs attention** card: unsupported, 360, cloud-only, damaged. Each item has its actions. A grouping-notes line closes the card.

Sticky footer: next-step hint and Continue.

## States

- Scanning: skeleton cards filling progressively.
- Nothing needs attention: the card collapses to one green line.
- Cloud download running: inline progress on that row.

## Data & API

- `/projects/{pid}/inventory`, `/cloud-files/download`, SSE `job.progress`.

## Acceptance

- Unsupported reasons come from the camera-profile catalog (`MEDIA_SUPPORT.md`), never from raw ffprobe errors.
