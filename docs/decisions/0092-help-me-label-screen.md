# 0092 — S24 Help me label: the dialog and its entry in the Library

- Status: accepted (M4 step 14g)
- Deciders: agent (autonomous; no human gate)

## Context

S24 is a dialog over the dimmed Library. It shows "Question n of 5" with a progress bar, thumbnails, the answers (Yes / No / Not sure, or a field), an optional name matched to the trip context, and Skip / Back / Next. Keys: 1/2/3 choose, Enter Next, Esc close. It ends with a done summary. ADR 0085 made the questions and answers (`/labeling-questions`) and left the entry point to this step. It also requires a name for Yes, since a link needs a label.

## Decision

- **Entry**: the Library shows an info banner once no analysis is running and there are open questions ("3 quick questions can make your labels better. Each one is optional.") with **Help me label** and **Not now**. Not now hides the banner until the Library is opened again.
- **The batch** shown is the one fetched when the dialog opened, and it stays fixed while it is answered. When the dialog closes, the questions and the trip details are fetched again, so a new batch can come later (ADR 0085).
- **Keys** belong to the dialog. Each question takes the focus (its chosen or first answer, else its field), and the summary's Close takes it at the end, so 1/2/3 and Enter work as soon as a question shows.
- **Answers are sent one at a time** with Next. Skip records a skip. Back shows an earlier question as answered or skipped, read-only, because the API takes one answer per question. A refused answer shows its reason, and the dialog stays on that question; one answered elsewhere already (another window) is passed over. The confirmation says what was recorded: trip details for a place or event, and a link only for Yes.
- **Same person**:
  - The name is "(optional)" until Yes is chosen. With Yes it is needed, because the link needs a label; the label says so and Next waits for it.
  - The trip context's people are offered as suggestions. A name that matches one (ignoring case) shows "Matches your trip details: “Maya — younger daughter, yellow raincoat”". The question payload's `people` now carries each person's description.
- **Place and event**: a field, with the note that the answer goes into the trip details.
- **The copy** repeats what ADR 0085 guarantees: faces are not stored or recognized, and answers only link clips.

## Consequences

- No new tables or data. The no-biometrics acceptance test (ADR 0085) covers everything the dialog can store.
