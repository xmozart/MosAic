# S7 — Trip Context

- **Reference:** `docs/ui/reference/` → S7-TripContext
- **Milestone:** M2

**Purpose.** Optional trip details that improve story and titles.

## Layout

Header with an Optional pill. Tabs: Quick paste | Details.

**Details**, two columns:

- left: trip name, parsed-result banner, editable day table (Day, date, place, notes); rows that came from parsing are tinted `accent-soft`
- right: People (initial avatar, label, description), Must include chips (user blue), Avoid chips (reject), Notes
Footer: Skip for now / Save. Subline: "won't re-run analysis".

## States

- Empty.
- Parsing (spinner on the Parse button).
- Parsed (new values highlighted).
- Partially filled.

## Data & API

- `/trip-context`, `/trip-context/parse`.

## Keyboard

- ⌘Enter in the paste box runs Parse.

## Acceptance

- Saving context re-runs only summary and labeling tasks (checked in the task log).
