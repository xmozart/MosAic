# 0087 — S15 Creating edit: the generation's steps and beats, live from its job

- Status: accepted (M4 step 14b)
- Deciders: agent (autonomous; no human gate)

## Context

S15 shows an edit being made: a step list (Finding candidates → Planning → Choosing shots → Fitting to target → Refining cuts → Checking → Rendering preview) with notes such as "412 → 186 candidates" and "7 beats", and the beats appearing as they are planned, with thumbnails, the one in progress highlighted (`docs/ui/screens/S15-creating-edit.md`, mockup S15-Creating). It offers Run in background and Cancel; a failure shows the reason in plain words and Retry. Until now a generation reported only a stage name.

## Decision

- **The generation publishes S15's view in its job's result**, under `creating`, as it goes (`generate.Creating`): the step (`planning`, `selecting`, `fitting`, `checking`), the moments retrieval looked at and the candidates it kept, the plan's beats as soon as the planner answers (title and intent), and, once shots are chosen, frames of each beat's first three shots (a kept sample inside each segment). `GET /jobs/{id}` already returns the result; no new endpoint.
- **Beats appear when the plan is ready.** The planner and the selector are one call each, so beats cannot arrive one by one; they appear together, and while shots are chosen the first beat without frames is highlighted, the later ones dimmed. Fitting and refining are one solver step and are shown running and finishing together.
- **The screen** (`/p/:pid/edits/:eid/creating?job=`) opens after Create in S14. It polls the job each second while it runs. Once the edit is made it starts the preview render (once) and follows it, then offers View storyboard (the preview, S17, until the storyboard screen arrives in 14c). Run in background returns to S13, whose card keeps the progress ring. Cancel cancels the job; a failed job shows its reason without an exception's name, with Try again; a cancelled one offers Start again (both regenerate the edit as a new job).

## Consequences

- S15 needs no SSE channel of its own: a one-second poll of the job is enough for a step list.
- The job's result keeps the last view, so a reloaded page shows where the generation was.
