# ADR 0016 — M0 render: exact chunks, stream-copy assembly, two-pass loudness

- **Status:** accepted (agent decision, M0 step 11)
- **Date:** 2026-10-05

## Context

`ARCHITECTURE.md §10` asks for a chunk renderer (one mezzanine per event at the timeline
format, cached by event hash and render profile) and an assembler (concatenation, audio
mix, loudness to −14 LUFS and ≤ −1 dBTP). M0 adds:
- nearest-frame conform, tone mapping, pillarbox and silence fill;
- the encoder order VideoToolbox → NVENC → openh264, with FFV1 for frame-exact tests;
- previews from proxies and finals from originals at 1080p SDR.

The spec leaves these open:
- how to cut sources frame-exactly, including across chapter files;
- how audio stays aligned over many chunks;
- the mezzanine format;
- how loudness is measured.

## Decision

1. **Cutting.**
   - Each event maps to one piece per chapter file it touches. A file's logical 0 is its
     first video PTS.
   - Each piece is read with a fast input seek 3 s before the cut, then `-copyts` and
     `trim`/`atrim` at absolute stream timestamps.
   - This is exact for edit lists, start offsets and chapter joins, without decoding from
     the start of long files.
   - Previews read the proxy, whose time 0 is logical 0.
2. **Conform and format.**
   - Each piece's timestamps are re-zeroed at its exact cut point, not at the first kept
     frame, so sub-frame phase is kept.
   - **Nearest-frame conform.** Timestamps are shifted by ½ output frame − ½ source frame,
     then `fps` with nearest rounding and `start_time=0` is applied.
     - `fps` keeps the last input frame that rounds into each output slot. With this
       shift, that frame is the one nearest the output instant, for faster sources
       (120 fps) and slower ones alike.
     - It is PTS based, so VFR sources resample correctly.
   - Then: scale to fit (even dimensions), HLG/PQ tone mapping (the proxy's zscale +
     tonemap chain), centred pad (pillar or letterbox), full-range to TV range, and
     Rec.709 tags. `fps` runs first, so a high-frame-rate source is scaled once per
     output frame, not once per source frame.
   - `tpad` (clone) and `trim` then make the frame count exactly the event's. `-frames:v`
     is not used, because it cuts the audio tail.
3. **Audio.**
   - Each chunk carries `round(frames · 48000 / rate)` samples of 48 kHz stereo: source
     audio with its gain and 2-frame fades, or generated silence when the event is muted
     or the source has none.
   - The count depends only on the chunk, so an unchanged event's chunk is reused by later
     versions. The assembler pads or trims the total to the edit's exact length. The
     drift is under half a sample per chunk.
4. **Mezzanine.**
   - Chunks are MOV files with the timeline rate's timescale (exact frame timestamps;
     Matroska's milliseconds would make the joined file variable frame rate). They hold
     H.264 from the preferred hardware encoder (no B-frames, keyframe at the start) and
     PCM.
   - The lossless test profile uses FFV1 + PCM.
   - A chunk is cached only after its frame and sample counts are verified exactly.
     Past the end of the media, an event holds the last source frame, never an empty
     piece.
   - Chunk keys hash: the event's source range, frames, audio and transform; the source
     files' fingerprints (or the proxy key); the render profile; the timeline rate; and
     `render/1`.
5. **Assembly.**
   - Chunks are concatenated with the concat demuxer, video stream-copied and re-timed
     onto the exact frame grid (`setts=ts=N·den`, timescale = rate numerator). The result
     is constant frame rate, and its frame and sample counts are verified.
   - Audio uses two-pass `loudnorm`: a measuring pass, then a linear apply to −14 LUFS
     integrated and a −1.5 dBTP true-peak target, a margin under the −1 dBTP limit.
   - Silence (measured below −70 LUFS) is left as it is.
   - Output is AAC 192k in MP4 (+faststart), or FFV1/PCM in MOV for lossless renders.
   - The result is measured again with `ebur128` and stored on the `render` row.
6. **Profiles.**
   - Preview: 1280×720 at 5 Mb/s, from the proxies.
   - Final: 1920×1080 at 14 Mb/s, from the originals.
   - The encoder is the first available of VideoToolbox → NVENC → openh264.
   - `--lossless` (hidden) selects FFV1 for frame-accuracy tests.
7. **Jobs.**
   - A render job has one `render.chunk` task per event (`gpu_encode` class, run in
     parallel and skipped when cached) and one `render.assemble` task.
   - The output goes to `renders/edt_NNNN/vNNN-<kind>-rNNNN.<ext>` in the workspace,
     never next to the originals. The file name is unique per render, so two renders
     never share a file.
   - A render whose job failed or was cancelled is reported with that status.
8. **API (M0 subset).**
   - `POST /edits/{eid}/preview`
   - `POST /renders {edit_id, version?, final?}`
   - `GET /projects/{pid}/renders`

   Presets, formats, destinations, cancel and re-render come with S19/S20 (M2).

## Consequences

- On the synthetic corpus, lossless final renders decode to exactly the EDL source frames
  (±1 where the source rate differs from the timeline rate). Frame and sample counts are
  exact, and loudness is within 1 LU of the target.
- A new version re-renders only events that changed.
- Transitions other than cuts, music, crops/reframing and speed changes are later
  milestones. The chunk key already includes `transform` and `speed`.
