# 0080 — Music bed: one track mixed under the edit, ducked under dialogue

- Status: accepted (M4 step 9c)
- Deciders: agent (autonomous; no human gate)

## Context

M4 asks for "a basic music bed (user track, fades, static level, simple ducking under detected speech)". ADR 0066 stores the request's `music` as the track's absolute path, a level in whole dB (−40 to 0, default −18) and fades in whole milliseconds, and says the path is checked where an edit is saved (inside a media root in server mode). Beat-synced cutting is M6. Originals and the owner's files are read only (invariant 1); a server reads files inside its media roots only (ADR 0035).

## Decision

- **Path checks.** Creating an edit (`POST /projects/{pid}/edits`) refuses a music path that is not absolute, not a file or not readable (422, `editing.music.check_path`). In server mode the path must lie inside a media root after resolving symlinks (403, `media_roots.confine`, as for LUTs), and the canonical path is stored. A render checks the track again (in server mode, that it is still inside a media root) and probes it for an audio stream, failing with a plain message when it has gone or has no audio.
- **The mix.** The music changes no cut, so it is mixed at assembly, after the chunks:
  - the track is looped (`-stream_loop -1`) and trimmed to exactly the edit's samples, set to its level, and faded in and out over its fades;
  - it ducks by a fixed 12 dB, with quarter-second ramps, wherever the edit plays dialogue: the heard windows of dialogue events (their J/L windows when split, ADR 0077), joined when at most half a second apart (twice the ramp, in whole frames, rounded up). The duck is a `volume` envelope over time computed from the timeline, not a compressor keyed on the edit's sound, so loud natural sound never pumps the music;
  - the edit's own sound is mixed in unchanged (`amix`, not normalized), and the mix is one exact-length PCM file;
  - loudness normalization then measures and normalizes the mix, so the edit still meets −14 LUFS and the true-peak limit.
- Every filter is LGPL libavfilter (`aresample`, `atrim`, `volume`, `afade`, `amix`); no sidechain or GPL filter.
- Chunks are unchanged and reused; only the assembly differs, and it runs for every render anyway.

## Consequences

- A track shorter than the edit loops without a gap; a longer one is cut at the edit's end under the fade-out.
- The level is static outside the ducks; dynamic or beat-aware music editing is M6.
- The music path stays in the request, so it enters the edit's key (ADR 0066); changing the track makes a new version.
