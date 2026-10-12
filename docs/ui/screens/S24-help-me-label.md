# S24 — Help Me Label

- **Reference:** `docs/ui/reference/` → S24-HelpLabel
- **Milestone:** M4

**Purpose.** Optional questions that improve labeling.

## Layout

Dialog over a dimmed Library. Header with "Question n of 5" and a progress bar.

Each question shows thumbnails and answer buttons, with an optional name field matched to trip context.

Footer: Skip / Back / Next.

## States

- Place question (field).
- Same-person question (Yes / No / Not sure).
- Event question.
- Done summary.

## Data & API

- `/labeling-questions`, `/labeling-questions/{qid}/answer`.

## Keyboard

- 1/2/3 choose an answer; Enter Next; Esc close.

## Acceptance

- Answers link clips through the `person_link` table only. There is no face recognition or biometric storage.

## M4 notes (ADR 0092)

- Entry: an info banner in the Library once analysis is done and questions exist (Help me label / Not now).
- With Yes, the name is needed (a link needs a label); otherwise it is optional.
