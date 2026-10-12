# 0084 — Final profiles (H.264, HEVC, ProRes) and the export sidecars

- Status: accepted (M4 step 12)
- Deciders: agent (autonomous; no human gate)

## Context

M4: "Final render profiles: H.264 and HEVC via hardware encoders, 1080p/4K, and a ProRes 422 master where the encoder is available. Exports include EDL JSON, SRT captions from the transcript, and a selection/rejection report." S19 offers three presets (Web H.264 / High quality HEVC / Master ProRes) with resolution, frame rate and loudness, "Also include: SRT, selection report, JSON", and disables a preset whose encoder is missing. Until now every render was H.264 (or FFV1 for lossless tests). Encoding uses platform hardware encoders; software x264/x265 are GPL and not used (CLAUDE.md).

## Decision

- **Codecs.** A render profile has a codec: `h264` (the default and every earlier render), `hevc` or `prores`.
  - Encoders, in preference order, each kept only when a trial encode works on this machine: H.264 as before; HEVC `hevc_videotoolbox`, `hevc_nvenc`, `hevc_qsv`, `hevc_amf`; ProRes `prores_videotoolbox`, then FFmpeg's own `prores_ks` (LGPL, software: a master is always possible).
  - H.264 and HEVC go in MP4 with AAC (HEVC tagged `hvc1` so Apple players open it); ProRes 422 (standard) goes in MOV with PCM audio and 10-bit 4:2:2 picture.
  - Chunks are encoded with the profile's encoder, so a final HEVC render concatenates HEVC chunks by stream copy, as H.264 does.
  - An H.264 profile's JSON is unchanged, so its chunk keys are too.
- **Resolution** comes from the export (1080p, 1440p, 4K), else from the request; **frame rate** is the edit's own (changing it would re-time every cut; S19 shows it read-only).
- **Loudness** is S19's choice for the export, else the request's: `web` −14 LUFS integrated, `tv` −23 LUFS (EBU R128), true peak −1.5 dBTP for both. Like the resolution it is render-only, and it is part of the assembly key.
- **The export's choices** (resolution, loudness, sidecars) are kept with the render, outside its profile's JSON (so chunk keys never see them), and S20's Re-render repeats the same export: codec, resolution, loudness and sidecars.
- **API names.** `POST /renders` takes `codec` (the API map's earlier `preset`: S19's Web H.264 / High quality HEVC / Master ProRes) and `sidecars[]` (earlier `include[]`); `fps` is not taken (the edit's own rate) and `dest` comes with S19's Save to.
- **Sidecars** for a final render, when asked for: written next to the render file once it is assembled, each downloadable from the render:
  - `.edl.json`: the version's JSON export (the timeline with exact times, invariant 7);
  - `.srt`: captions of the speech that is heard - transcript words inside each event's heard window (its J/L window when split), placed on the timeline in whole milliseconds; a cue is at most two lines of 42 characters and 7 s, breaks at sentence ends and pauses;
  - `.report.txt`: the selection and rejection report (`mosaic report`'s text) with every rejected segment.
  - A cancelled render or a deleted file takes its sidecars (and any half-written one) with it.
- **Availability** for S19: `/system/info` lists the working encoders per codec; a preset without one is disabled with that reason.
- "Save to" another folder is the S19 screen's (14g): it copies the finished files where the owner chooses, within media roots on a server.

## Consequences

- A ProRes master is possible on every machine; HEVC needs a hardware encoder (none on the Linux CI runners, so its tests run where one works).
- Captions exist only where a transcript does (speech detected and transcribed).
