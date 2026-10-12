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

- Infeasible locks warning in the summary panel (not applicable in v1: the wizard makes a new edit, which has no locks; the warning is S16's, ADR 0093) ("Locked shots add up to 5:22 — Allow 5:30 / Review locks").
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

## M2 notes (ADR 0048)

- Steps 3–5 are shown disabled, and Next on step 2 goes to step 6.
- Step 2's More options (the arc template and beats), locks and must-include chips wait for M4.
- Custom (step 2) offers the nine other story presets.
- Create returns to S13 (S15 is M4).

## M4 notes (ADR 0066)

- Step 4's More options hold the two rules the mockup doesn't show: "Unique moments over technical quality" and "Allow long cinematic holds".
- Step 5's music source is None or Choose track. Choose folder waits for M6's music library.
- Defaults are PRODUCT.md §4's; the mockup's filled-in example is not the default state.
