# 0089 — S17 findings: the panel, the suggested fix in words, Regenerate with fixes

- Status: accepted (M4 step 14d)
- Deciders: agent (autonomous; no human gate)

## Context

S17's right column becomes the findings list (`docs/ui/screens/S17-preview-findings.md`, mockup S17-Preview). It has Apply all / Ignore all, a FindingCard per finding (Issue or Suggestion, a timecode that seeks, the text, the suggested fix, Apply / Ignore, "Applied in vN"), Regenerate with fixes, a "Version N created · Undo" toast, finding markers on the scrub bar, and N / P / A keys. ADR 0081 stores findings with their fix as storyboard ops, but nothing said how the fix reads or what "Regenerate with fixes" does.

## Decision

- **The fix in words.** `GET /findings` items gain `fix`: the finding's ops in plain words, such as "Replace it with DSC_0932.MOV" (the alternative's file) or "Remove it". It is `null` when the finding has nothing to apply. A finding without a fix offers Ignore only.
- **Issue or Suggestion.** `blocking` and `warning` are Issues (`reject`); `info` is a Suggestion (`info`). Markers on the scrub bar use the same colours, for open findings only. AI-review findings are marked "AI review".
- **Regenerate with fixes** (`POST /edits/{eid}/findings/regenerate`, 202):
  1. it applies every open finding that has a fix, as one child version (as Apply all does);
  2. it then regenerates, in one job, the beats that hold an open Issue with no fix (one task per beat, run one after another, each keeping its locks; ADR 0069).
  
  The beats come from the findings the owner was looking at, because the AI critic's notes are not made again for a child version, and beat ids hold across versions. Suggestions regenerate nothing, and a beat whose shots are all locked is left alone. The endpoint returns `409` with unsaved storyboard changes and `422` when there is nothing to fix or regenerate. The draft's `regenerating` includes these beats while the job runs.
- **Undo** in the "Version N created" toast reverts to the version the fix was applied to (`/revert`, ADR 0083). This makes a new version, so history is never rewritten.
  - Only the latest such toast offers Undo; an older Undo would drop the fixes after it.
  - When Regenerate with fixes also starts a job, the toast has no Undo, because an undo would land under the beats being regenerated.
- **"Applied in vN"**: `GET /findings?version=` also lists, under `applied`, the earlier findings whose fix made this version. After a fix, the new version is shown with those cards (dimmed, "Applied in vN") above its own findings.
- **The regenerate job** runs its beats one after another. A beat that cannot be regenerated (for example, its pool has run dry) fails the job, and the beats after it are cancelled; the ones before it are kept as their versions. The draft lists all of the job's beats as `regenerating` until the job ends. A job paused at its AI cost limit is followed, not reported as failed.
- **Keys**: N / P move the focus between findings and seek to each. A applies the finding that has the focus, only while the focus is on it.
- **The side column** switches between Findings (first) and Why these shots (M2's selection report), so the report stays one click away.
- **An older version's findings** are listed, but Apply and Ignore wait for the latest version, where fixes go.

## Consequences

- Regenerate with fixes can cost AI calls, one selector call per beat. Apply all never does.
- Findings that are about the whole edit and have no event (such as duration) cannot point to a beat. They are only ever ignored or resolved by hand.
