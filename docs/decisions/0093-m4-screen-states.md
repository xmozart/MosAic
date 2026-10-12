# 0093 — M4 screen states: S14's lock warning belongs to S16

- Status: accepted (M4 step 15)
- Supersedes: the S14 consequence of ADR 0068 and the "Locks" bullet of ADR 0086
- Deciders: agent (autonomous; no human gate)

## Context

M4 acceptance 6 asks for a story for every state the M4 screen docs list. S14 lists "Infeasible locks warning in the summary panel ('Locked shots add up to 5:22 — Allow 5:30 / Review locks')". In MosAic's v1 flow:
- S14 always creates a **new** edit, including from S13's "Start from" and S16's "Change settings" (ADR 0088).
- A new edit has no locks. Locks belong to an edit's storyboard, and generation starts without any (ADR 0068, 0069).

So the wizard can never show that warning: there are no locked shots for it to add up.

ADR 0068 and ADR 0086 planned otherwise. They meant "Change settings" to open the wizard on the **existing** edit, passing its id to the estimate so its locks could be added up. ADR 0088 then made "Change settings" start a new edit from the same settings, and left that plan without a place to happen. This ADR records the change instead of leaving it implicit.

## Options

1. Carry the source edit's locks into the new edit, so the wizard can warn about them. This needs generation to start from pinned shots, which today only regeneration does: new solver and generation work late in the milestone.
2. Keep the warning where locks exist. S16 shows the infeasible-locks warning from the draft's lock budget (ADR 0088), and changing an edit's length ("Make it N seconds") reports locks that can't fit.

## Decision

Option 2. The S14 state is recorded as not applicable in v1. The lock warning is S16's ("Your locked shots run 0:40 past the longest this edit can be"). The acceptance test (`tests/acceptance/test_m4_screens.py`) maps the S14 state to this ADR instead of a story. Every other listed state of S13–S19 and S24 maps to a story with baselines in both themes.

## Consequences

- This diverges from the approved mockups. S14b-WizardStory shows "Locked shots add up to 5:22 — longer than your 5:00 target. Allow 5:30 or review locks", and S14-Wizard and S14b show a "2 locked shots" summary line. Both are listed for the owner at G6 (OPEN_QUESTIONS Q-4, and the M4 report).
- If a later milestone lets the wizard change an existing edit's settings in place, keeping its locks, the S14 warning comes back with it. The estimate already has the lock budget to draw on (`resolve.lock_budget`).
