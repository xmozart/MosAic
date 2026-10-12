# 0086 — S14 in full: steps 3–5, custom beats, and the music track card

- Status: accepted (M4 step 14a)
- Deciders: agent (autonomous; no human gate)

## Context

S14 is M4 "full": step 2's More options (arc template, drag-ordered beats), step 3's weight sliders ordered by library frequency, step 4's pace, transitions, rules and photo share, and step 5's sound toggles, music source, track card with waveform and level (`docs/ui/screens/S14-create-edit-wizard.md`, mockups S14, S14b, S14c). The request's fields exist since ADR 0066. Two things in the mockups are not spelled out by the spec: the beats list shown under "Classic travel", and the infeasible-locks warning in the summary panel.

## Decision

- **Steps 3–5 are open**, built from new components on the tokens: `WeightSlider` (five segments filled up to the value, ARIA slider, ←/→), `PaceSlider` (six stops and the "about n s per shot" readout), `CheckboxRow` (the rules), `LevelSlider` (the music level in whole dB, ←/→ one dB, Shift six), `BeatsEditor` and `MusicTrackCard`.
- **Step 3** shows the six categories the library has most (`GET /projects/{pid}/edit-categories`), then the rest as chips; a chip adds its slider, and All categories adds them all. Neutral is never sent (ADR 0066).
- **Step 2's beats.** With an arc template the planner names the beats from the footage, so the list is shown and edited only for **Custom beats** (2–12 named beats, drag or the arrow buttons to reorder); the mockup's beats under Classic travel stand for that list. Create waits until every beat has a distinct name of two characters or more.
- **Step 5's track.** "Choose track" opens the desktop's file dialog; in a browser the owner types the track's full path (a server checks it against its media roots, ADR 0080). The card's name, length, sample rate and waveform come from `POST /api/music/probe {path}` → `{name, duration_ms, sample_rate, peaks[48]}`: the same path checks as an edit's music, the file only read: its first half hour at most, as 400 Hz mono samples, so the request stays short (a longer track's waveform shows its first half hour; its length is the whole). A file that fails to probe or decode, or takes too long, is refused in plain words (422), never a server error. Choose folder waits for M6 (ADR 0066).
- **The summary panel** adds lines for the weights ("More wildlife and people", "Less selfies"), the rules turned on beyond the defaults, transitions, photo share, sound and music, all from the request (S14's single source).
- **Locks.** A new edit has no locks yet, so the infeasible-locks warning has nothing to show in this wizard; it belongs to a wizard started from an existing edit's storyboard, which comes with S16 (14c).

## Consequences

- Every field of the M4 request is reachable from the wizard; the backend validates them as before.
- `POST /api/music/probe` is a small synchronous read in a request handler, bounded by the track's length; long work still runs as jobs.
