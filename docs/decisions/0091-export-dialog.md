# 0091 — S19 Render final: estimates, encoder availability, Save to

- Status: accepted (M4 step 14f)
- Deciders: agent (autonomous; no human gate)

## Context

S19 is a 900 px dialog with three presets (Web H.264 / High quality HEVC / Master ProRes 422), each with a size and time estimate. It also has resolution, frame rate and loudness, the extra files to include, Save to, and an encoder note. A preset whose encoder doesn't work here is disabled with a reason, and an unwritable destination is an error. ADR 0084 made the final profiles and sidecars, but nothing gave estimates, and the files stayed in the workspace's `renders/`.

## Decision

- **`GET /edits/{eid}/export?version=`** returns:
  - the version's length, frame rate and defaults (resolution, loudness);
  - for each preset at each resolution: its size, its time, and whether its codec can be encoded here (`working_encoders`, with the encoder that will be used);
  - where files go.

  Sizes come from the final profiles' bitrates (H.264 and HEVC), and from Apple's ProRes 422 data rate scaled by pixels and frame rate. Audio is added. Times come from this computer's benchmark (its 720p pass per footage minute, scaled by frame size) and are `null` without one. Both are shown with "≈" (`render/estimate.py`).
- **Frame rate** is the edit's own, shown and not changeable (ADR 0084). **Resolution** offers 720p to 4K. **Loudness** is Web −14 or TV −23 LUFS.
- **Also include**: SRT, the selection report and the edit data (JSON) are ADR 0084's sidecars. The NLE timeline is shown disabled, "Coming later".
- **Save to** (`POST /renders` `save_to`), on the desktop only:
  - The owner picks a folder in the native dialog. The API takes it only if it is an absolute, existing folder this app can write to; otherwise it returns 422 with the reason, which the dialog shows.
  - When the render is done, the video and its sidecars are copied there as "‹edit name› v‹N›.ext". A file already in the folder is never replaced; the copy becomes "(2)" and so on, using exclusive create.
  - The API refuses a folder inside the trip's footage (the next scan would take the copy for a clip); the trip's own MosAic folder is allowed.
  - A copy that fails leaves the render done, with `save_error` beside it, and removes whatever part of the export it had copied (all of it or none). S20 shows "Saved to …" or the error, and a Re-render saves to the same folder.
  - A render that reuses an earlier identical file (ADR 0083) never inherits that render's copy record.
  - On a server, the files are downloaded from Exports (S20). The API refuses `save_to` with 422, and a server never acts on a `save_to` stored by a desktop (in a Re-render, or a render already queued).
- The footer says "Renders from your original footage" with the encoder used. Every final render conforms from the originals, as before.

## Consequences

- Opening the dialog runs the encoder trials once per process, if they haven't run yet (the follow-up from step 12: warm them at startup).
- Copying a large ProRes file takes time after the render. It happens inside the assemble task, so the job ends only once the copy is made.
