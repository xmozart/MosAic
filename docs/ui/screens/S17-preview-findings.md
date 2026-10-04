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
