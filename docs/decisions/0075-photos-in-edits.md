# 0075 — Photos in edits: stills, pan and zoom, blurred fill

- Status: accepted (M4 step 6)
- Deciders: agent (autonomous; no human gate)

## Context

M4 adds photo `still` events with pan/zoom motion, blurred fill for orientation mismatch, and a photo share preference. Acceptance 4: a photo-heavy request (photo share "many") mixes stills and video with no orientation artifacts. ARCHITECTURE.md §9 sketches a still event: `kind: still`, a duration in frames, and a motion with start and end crop rectangles plus an easing.

Photos are analyzed as one-frame clips, with time base `1/1`, one segment at tick 0, and a vision observation (ADR 0025). They are grouped into bursts and into captures shared with video (ADR 0026). Retrieval used to read video only. FFmpeg's `boxblur` is GPL, and the LGPL build may not decode HEIC or raw photos.

## Decision

- **Candidates.** Photos and Live Photos are candidates unless the request's photo share is "none".
  - A burst gives only its recommended frame.
  - A photo in a capture with video is that video segment's look-alike, so it is used only when footage runs short (as similarity groups are), unless the owner picked it.
  - **"many"** adds +1 to a photo's ranking and tells the selector to use plenty of stills.
  - **"some"** (the default) lets photos take at most a quarter of the AI's candidates: the best photos by rank. The owner's picks and locks always stay. So a photo-heavy library never crowds out its video.
  - **Footage for the look-alike fallback is video:** photos never stand in for it (their 5 s each is not usable footage).
  - **A storyboard's lock always wins:** a locked burst frame or capture twin stays a candidate in its own right (invariant 10).
  - **Trip days** keep the project's numbering: day 1 is the first video's date (as in deepen scopes and day summaries). A photo taken before it has day 0 ("day ?"), never a negative day.
  - A photo's categories include `photos`.
- **Timing.** A still holds 2 to 5 seconds, set by the pace through the solver, which picks a length within those bounds.
  - It has no source range: the refiner places nothing, and landing on the target moves its length only within 2–5 s.
  - It is never cut into a jump with a neighbour.
  - It can be locked. Its pin has a zero-length source range; only a photo's pin (time base `1/1`, at 0) may have one.
- **The event** is `kind: still`, with:
  - `duration` in frames;
  - a source range of 0–0 in the photo's `1/1` time base;
  - silent audio;
  - `motion` with `start` and `end` rectangles in thousandths of the frame. The rectangles hold at any output size and are integers (invariant 3). Stills alternate a slow push in (the full frame to the middle 85 %) and a pull out, with an ease in and out.
  - Subject-aware motion, which puts the rectangles on the subject, comes with M4 step 7's saliency.
- **Rendering.** A still chunk is made in two steps:
  - **Pillow** decodes the photo in display orientation (EXIF applied, so never sideways). It makes a canvas of the output's shape at 1.5 × its size (the long side capped at 6,144), so the motion never upscales.
    - A photo within a third of the output's shape (plus a 1 % margin) fills the canvas with a centre crop: 4:3 and 3:2 photos in a 16:9 edit, as a Ken Burns crop would. This is looser than video's 25 % (ADR 0046), because phone photos are 4:3.
    - A still keeps this rule even when the profile crops every video clip (`fill: crop`, a 9:16 reel of landscape footage). A portrait photo in a landscape edit is never cut to a sliver.
    - Any other photo sits whole on a blurred, darkened copy of itself (the blurred fill). It is never stretched and never has bars. The blur is Pillow's Gaussian blur on a small copy, never FFmpeg's GPL `boxblur`.
  - **FFmpeg** loops the canvas through `zoompan` at the timeline rate, over exactly the event's frames at the output size, with generated silence. As with every chunk, frame and sample counts are verified. A still chunk is keyed by the photo's fingerprint, its frames, its motion and the profile (`still/1`).
  - Previews and final renders both read the original photo, which is only read (invariant 1). Photos have no proxies.
- **Frame-exactness checks** (`check_render`) skip stills: a still has no source frames to match.
- **Stills never count toward the edit's render shape** (ADR 0046's dominant shape). So photos never turn a video edit into one where every clip is cropped.
- **Small things:**
  - The report shows a still as "photo".
  - A photo's video twin is part of the edit's inputs digest.
  - The canvas PNG is written fast (compression level 1), because FFmpeg reads it for every frame.
  - Motion rectangles must keep the frame's shape (`w = h` in thousandths).

## Consequences

- In `make ci`, a photo-heavy edit renders its still upright and whole, on a blurred fill, in the middle of the video events, with an exact frame count.
- Live Photo motion is not used: the still is shown. Using the motion is a later choice.
- Known limits:
  - `zoompan` positions in whole pixels, so a slow push can step about two thirds of an output pixel per frame on a 1.5× canvas.
  - Photos' colour profiles are not converted, so Display P3 photos may look a little flat.
  - Both are polish for later.
- Default edits (photo share "some") can now contain stills.
