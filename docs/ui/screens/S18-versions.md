# S18 — Versions

- **Reference:** `docs/ui/reference/` → S18-Versions
- **Milestone:** M4

**Purpose.** Browse, compare and revert versions.

## Layout

**Left:** `VersionList` (who: AI/You, reason, time, duration).

**Right:** compare header (Synced / Independent, Revert), two players, a "What changed" list with Replaced / Trimmed / Moved / Removed tags and timecodes.

## States

- Single version (compare disabled).
- Comparing.
- Reverting (creates a new version, never a destructive change).

## Data & API

- `/versions`, `/compare`, `/revert`.

## Acceptance

- Revert produces vN+1 equal to the target (render cache hit).
