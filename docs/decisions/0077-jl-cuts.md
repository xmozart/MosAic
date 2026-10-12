# 0077 — J- and L-cuts: the video cut moves, the audio stays on its words

- Status: accepted (M4 step 8)
- Deciders: agent (autonomous; no human gate)

## Context

M4 asks for a cut refiner v2 with "J-cuts and L-cuts for dialogue (audio lead/lag up to 1 s) and speech-aware in/out". Until now every event's sound ran exactly under its picture. The refiner already snaps a dialogue shot to sentence boundaries and every shot's cuts out of words (ADR 0015), and the critic counts a cut inside a word or a sentence as a blocking finding.

A J-cut lets the next shot's sound start while the previous picture is still on screen. An L-cut lets a shot's sound run on under the next picture. Either way, the sound and picture cuts of one boundary sit at different timeline frames.

## Options

1. **Extend the audio.** Keep the video cuts and take extra source audio before a dialogue shot's in point, or after its out point. The extra second is whatever the source holds there, which may be someone else's half sentence, so a speech-aware cut would need the transcript beyond the usable range.
2. **Move the video cut.** Keep each shot's audio window exactly where the refiner snapped it, on sentence and word boundaries, and move only the picture cut. The neighbouring shot's picture grows by the same frames, so the edit's length is unchanged.

## Decision

- **Option 2.** A J- or L-cut never changes what is heard: every audio window is still the refiner's, so speech-aware in and out points and the critic's word and sentence checks hold as before. The critic checks the audio windows.
- **Where.** At a boundary between a dialogue shot and a non-dialogue neighbour (a video or a still):
  - into dialogue, a **J-cut**: the neighbour's picture runs on and the speaker's picture starts later, so the first words are heard over the neighbour;
  - out of dialogue, an **L-cut**: the speaker's picture ends earlier and the neighbour's starts earlier, so the last words are heard over the neighbour.
- **How much.** `min(1 s, a quarter of the dialogue shot, its frames above the pace's minimum, the neighbour's room)`, in whole timeline frames. Under 6 frames there is no split. The neighbour's room is its usable range for a video (start or end side), never onto a camera jolt (an L-cut never pulls a settled in point back onto the jolt `settle` slid past) and never longer than its pace's maximum; for a still, its 2–5 s. A moved in point goes onto the source frame grid, as the refiner's `align` places it.
- **Locks.** A lock pins the window that is heard, the refiner's speech-safe cut, not the moved picture. A locked shot then plays sound and picture together.
- **Never** at a locked or pinned shot (its cut is exact, ADR 0068), between two shots of one recording (jump-cut rules), or between two dialogue shots.
- **Timeline.** A split event's `audio` gains its own window, in the event's own units: `source_in`/`source_out` (SourceTime) and `timeline_in`/`timeline_out` (TimelineTime). An event without a split has none, so earlier versions and unchanged events keep their keys. Audio windows are contiguous and cover the timeline exactly, as the video events do, and map to an OTIO audio track.
- **Chunk keys.** A video chunk's key leaves out the audio window, so a split event's picture is reused wherever it sits; the audio chunk's key covers the window.
- **Rendering.** A version with any split renders a separate audio-only chunk for every event (PCM, exactly `samples_for(audio frames)` samples, the event's gain and fades; silence for stills and muted events). The assembler concatenates the video from the event chunks and the audio from the audio chunks. A version without a split renders exactly as before, with the same chunk keys and the same assembly.
- Audio chunks are made in the event's `render.chunk` task and cached under their own key (event audio window, sources, profile), so the job DAG is unchanged. The audio window must lie in the same files as the picture, which it does: it is the window the refiner placed inside the usable range.

## Consequences

- Dialogue gets the overlapping sound of a cut film without any word cut off, and without changing the edit's length.
- A split moves picture cuts by up to 1 s. The video window of the neighbour grows into its usable range, never past it.
- Renders of versions with splits run one more short FFmpeg process per event (audio only).
- Transitions (step 9a) must not put a dissolve on a split boundary; a dissolve boundary gets no split.
