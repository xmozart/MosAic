# 0081 — Findings: critic v2 with fixes, applied as child versions

- Status: accepted (M4 step 10a; the AI critic is step 10b)
- Deciders: agent (autonomous; no human gate)

## Context

M4 asks for a "deterministic critic with findings in the UI" and a findings UI with "Apply all, apply individually, Ignore. Each applied finding creates a child version." ARCHITECTURE §13 lists a `finding` table (severity, timecode, text, suggested op, status open/applied/ignored, applied_in_version). Until now the critic's findings were JSON on each version, with no fix and no status. The storyboard's draft ops (ADR 0067) already express every change a fix needs, and user decisions override AI (invariant 10).

## Decision

- **Critic v2.** A finding about one shot names it (its selection ref, and the event id once the timeline exists) and carries its fix as storyboard ops:
  - **repetition**: the later of two look-alike shots within five is replaced by its first alternative that is not in the edit, else removed;
  - **shaky_shot** (new): a shot shakier than 90 % of the project's is replaced by an unused alternative (a warning); without one it is an info note with nothing to apply;
  - a shot the owner locked, pinned or chose (USE), or one cut together with such a shot, never gets a fix (invariant 10);
  - a later shot that repeats several earlier ones is one finding, and no two fixes offer the same alternative;
  - the other findings (duration, mid-word, truncation, jump cut, REJECT used, beat coverage) stay as before, without a fix.
- **Rows.** Every version's findings are recorded in `edit_finding` (migration `e3a7c9f1b250`, which also turns the findings of every older version into open rows) when the version is made, by generation and by saving a draft (`findings.record`). The version's `findings` JSON stays as the critic's output; status lives in the row: `open`, `applied` (with `applied_in_version`) or `ignored`. Each row has a ULID for the API.
- **Applying** one, several ("apply all": every open finding with a fix) or none:
  - only findings on the latest version, and only with a clean storyboard (409 otherwise): a fix is never folded into changes the owner has not saved;
  - each finding's ops are tried on the storyboard first; a finding whose ops no longer fit (its shot was removed, is locked now, or its alternative is gone) is skipped and reported, the rest go in;
  - the fixed storyboard is timed outside the writer; then one write transaction checks the draft is still clean, adds the ops, commits one child version (`creator: user`, reason "Applied: …") whose own findings are recorded afresh, and marks the applied findings with that version. Any failure leaves the draft and the findings as they were.
- **Ignoring** marks open findings ignored; nothing else changes.
- The API is in `docs/ui/API_MAP.md` (S17).

## Consequences

- S17 can show findings with Apply and Ignore and "Applied in v3"; Undo is a revert to the parent version (step 11).
- Fixes are ordinary storyboard ops, so every guard of the storyboard applies to them (locks, alternatives from the pool, user order), and the solver times the result.
- A finding's text names segment refs for now; S17 shows its timecode and event.
