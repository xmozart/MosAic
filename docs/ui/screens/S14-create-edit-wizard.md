# S14 — Create Edit Wizard

- **Reference:** `docs/ui/reference/` → S14-Wizard, S14b-WizardStory, S14c-WizardSteps
- **Milestone:** M2 basic (steps 1, 2, 6), M4 full

**Purpose.** Turn a few goals into an edit. The Simple path takes under 30 seconds.

## Layout

**Three columns:** `WizardStepNav` (230 px), the current step, and `EditSummaryPanel` (340 px). The primary "Create edit" is always available in the summary panel.

**Step 1:** duration chips, strict toggle, `AspectPicker`, More options (resolution, fps).

**Step 2:** 8 `StoryPresetCard`s with the user's own collages; chronology segmented control; More options (arc template, drag-ordered beats).

**Step 3:** the 6 most relevant `WeightSlider`s for this footage, then More categories.

**Step 4:** `PaceSlider` with readout, transitions, rule checkboxes, photo share.

**Step 5:** dialogue, natural sound and wind toggles; music source; track card with waveform; music level.

**Step 6:** instructions textarea with idea chips.

## States

- Infeasible locks warning in the summary panel ("Locked shots add up to 5:22 — Allow 5:30 / Review locks").
- Preliminary analysis banner: Create now (preliminary) / Wait.
- Start from a template or previous edit.
- Estimate loading.

## Data & API

- `/presets`, `/edits/estimate`, `POST /edits`, `/edits/{eid}/generate`.

## Keyboard

- ⌘Enter = Create edit; ⌘↑/⌘↓ change step; ←/→ adjust the focused slider.

## Acceptance

- The summary panel text is generated from the request object (single source).
- Category ordering comes from library tag frequency.
