# 0078 — Transitions: dips as fades, dissolves as their own chunks

- Status: accepted (M4 step 9a)
- Deciders: agent (autonomous; no human gate)

## Context

ADR 0066 maps the wizard's transition choices to what an edit uses:
- **Mostly cuts** (`cuts`, the default): straight cuts, with a short dip to black only at the opening, the closing and around title cards;
- **Soft dissolves** (`dissolves`): short dissolves where one beat changes to the next, with cuts inside beats;
- **Minimal** (`minimal`): cuts only.

ARCHITECTURE §10 renders each event as a chunk at the timeline format and concatenates the chunks, with "handles for transitions". A dissolve shows two pictures at once, so it cannot sit inside one event's chunk. Events must keep exact integer frames (invariant 3), and unchanged events must keep their chunk keys (invariant 9).

## Decision

- **The edit's frames never change.** A transition is drawn over frames the events already have.
- **A dip** is a fade from black over an event's first frames (`transition_in: {"type": "dip", "frames", "rate"}`, on the first event), or to black over its last frames (`transition_out` of type `dip`, on the last event).
  - It is half a second, at most half the event.
  - It is rendered inside the event's own chunk: frame-exact `fade` filters, with the sound fading with it.
  - Dips around title cards come with the title cards (step 9b).
- **A dissolve** of D frames into the next event (`transition_out: {"type": "dissolve", "frames": D, "rate"}`) is half a second (14 frames at 29.97), centred on the cut.
  - The refiner chooses one only where a beat changes, between two videos (not a photo), when the outgoing shot has D/2 frames of usable picture past its out point and the incoming shot has D/2 before its in point, never across a camera jolt (as for J/L cuts, ADR 0077), and when each picture keeps frames of its own. Otherwise the cut stays a cut, with a note.
  - **Rendering.** Each picture's own chunk is D/2 frames shorter on the dissolve's side. A separate dissolve chunk of exactly D frames blends the outgoing picture (from D/2 before its cut to D/2 past it) into the incoming one (from D/2 before its in point) with `xfade`. Its sound is the outgoing sound fading out mixed with the incoming one fading in (`amix`, not normalized). The chunk task of the outgoing event makes it, so the job DAG is unchanged, and the assembler puts it between the two pictures.
  - Its key is the keys of its two sides, so it is reused when neither picture changes.
  - The handle past the outgoing cut is measured from the out point, with the same rounding (`core.time.frame_start_ticks`) as the refiner's check, so the renderer never reads beyond what was checked. A dissolve has an even number of frames; an odd one is refused.
- **J- and L-cuts** are not made at a dissolve boundary (ADR 0077). In a version with J- or L-cuts the sound comes from the audio chunks, so a dissolve there blends only the picture, and the sound cuts at the boundary with its usual short fades. A dip fades the event's audio chunk too, so the sound goes with the picture either way.
- **Keys.** The chunk key of an event with no transition is unchanged. A dip enters its event's key. A trimmed picture's key follows from its shorter range.
- **The render check** (`devtools.render_check`) does not match frames inside a dip or a dissolve: there is no clean source frame to match there.
- `EDIT_VERSION` is `edit/3`: the default request now ends its edits with dips, so regenerating an unchanged request makes a new version rather than returning the stored one.

## Consequences

- "Soft dissolves" blends beat changes where the footage has room, without changing timing, the storyboard or locks.
- A dissolve costs one more chunk per beat change. Revisions that do not touch either picture reuse it.
- Dissolves never use footage outside a clip's usable range, so short clips used almost whole are joined by cuts.
- Dissolves into and out of photos wait for a later step: a still chunk has no picture beyond its own frames.
