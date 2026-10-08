# S17 — Preview Findings

- **Reference:** `docs/ui/reference/` → S17-Preview
- **Milestone:** M2 (player + report), M4 (findings)

**Purpose.** Watch the edit and act on critic findings.

## Layout

**Left:** large player with beat-colored segments on the scrub bar, finding markers (issue = reject, suggestion = info), playhead, version selector; `EditFacts`; actions Open storyboard / Export… / Render final.

**Right (400 px):** findings list with Apply all / Ignore all and Regenerate with fixes.

## States

- Preview rendering (progress over the player).
- No findings: "Looks good — no issues found".
- Fix applied: the card shows "Applied in v3", plus a toast with Undo.

## Data & API

- `/edits/{eid}`, `/findings`, `/findings/{fid}/apply|ignore`, `/preview`.

## Keyboard

- N / P jump to the next/previous finding; A applies the focused finding.

## Acceptance

- Clicking a finding's timecode seeks the player.

## M2 notes (ADR 0049)

- The right column is the selection report: "Why these shots", with Shots, Not used and Rejected. Findings replace or join it in M4.
- Opening a version without a preview starts one.
- "Open storyboard" is disabled until M4. "Export…" is **Exports** (S20).
- Render final becomes Download final when the render is done.

