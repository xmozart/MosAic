# S16 — Storyboard

- **Reference:** `docs/ui/reference/` → S16-Storyboard
- **Milestone:** M4

**Purpose.** Review and shape the story.

## Layout

Header actions: Change settings / Regenerate story / Preview. `DurationBar` with the target marker.

A 3-column grid of `BeatCard`s. Shot chips open a `ShotPopover` with reason, alternatives (with why-not), Lock, Remove and Play.

Drag shots within or between beats; drag beats to reorder.

## States

- Locked beat (`user` border and lock pill).
- Regenerating beat (shimmer; the others stay interactive).
- Infeasible-locks inline warning.
- Draft has unsaved changes (header shows "Unsaved changes · Save version").

## Data & API

- `/edits/{eid}`, `/draft/ops`, `/beats/{bid}/regenerate`, `/shots/{evt}/alternatives`, `/versions`.

## Keyboard

- ⌘Z / ⇧⌘Z undo/redo · Space plays the hovered shot · L locks the focused shot · Delete removes it.

## Acceptance

- Every draft op is undoable.
- Locks survive regeneration (M4 acceptance test 2).
