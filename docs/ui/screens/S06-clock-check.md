# S6 — Clock Check

- **Reference:** `docs/ui/reference/` → S6-ClockCheck
- **Milestone:** M2

**Purpose.** Fix wrong camera clocks using evidence pairs.

## Layout

880 px dialog. Intro line, then one card per suspect device. Each card has:

- device name and verdict ("Appears 5 h 00 m ahead")
- an evidence pair: two frames with their capture times, joined by a compare icon
- explanation ("These look like the same moment: …")
- offset stepper
- segmented Accept suggestion / Adjust / Leave as is
Consistent devices are listed in one green line. Footer: Skip — I'll fix it later / Apply.

## States

- No suggestion available: manual stepper only.
- All consistent: a single confirmation and Continue.

## Data & API

- `/devices/suggestions`, `PUT /devices`.

## Keyboard

- Tab through devices; +/− adjust the focused stepper by 1 h (Shift: 1 min). The `=` key (and numpad `+`) means + 1 h; Shift+`=` (the `+` key on US layouts) means + 1 min (ADR 0040).

## Acceptance

- Applying offsets updates day grouping across Library without re-analysis.
