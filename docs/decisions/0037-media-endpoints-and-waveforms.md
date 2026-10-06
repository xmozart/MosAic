# 0037 — Media endpoints for the browser, and the waveform stage

- Status: accepted (M2 step 4)
- Deciders: agent (autonomous; no human gate)

## Context

M2 lists "Video playback: proxies served with HTTP range requests". API_MAP lists `/media/{pid}/proxy/{aid}` (HTTP range), `/frame/{sample_id}`, `/waveform/{aid}` and `/filmstrip/{aid}`. COMPONENTS.md's Player, Filmstrip and Waveform use them.

Invariant 8 says HTTP handlers only create, query or cancel jobs, so a waveform cannot be decoded at request time.

## Decision

- **`proxy`** serves the clip's preview proxy as `video/mp4` through Starlette's `FileResponse`.
  - It answers `Range` (206, suffix ranges, multipart ranges) and returns 416 for an unsatisfiable range.
  - The proxy is `load_proxy`'s preview choice: Balanced 720p, else Quick, without a LUT that is not built yet (ADR 0028).
  - A clip with no proxy yet, or an unknown clip, gets 404 "No preview yet".
  - Originals are never served.
- **`frame`** returns a sample frame's JPEG artifact (`SampleFrame.image_key`).
- **`filmstrip`** returns up to `n` kept sample frames (default 8, at most 64), evenly spread, optionally within `[start_ticks, end_ticks)`.
  - The response is `{tb, frames: [{sample_id, ticks}]}`. Times are exact; the client builds frame URLs.
  - Hover-scrub uses sample frames, never video decode (S10).
- **`waveform`** reads the artifact of a new L1 stage, `media.waveform` (per video clip, after the proxy, CPU).
  - The stage decodes the proxy's audio to 8 kHz mono, streamed one second at a time.
  - A bucket is a whole number of samples: 400 (50 ms), growing so a clip never has more than 36,000. Its length is therefore exact: `{"ticks": 400, "tb": "1/8000"}`.
  - Peaks are 0–255, square-root scaled, and stored base64 in JSON.
  - The key is the proxy key plus the stage config and version, so it is idempotent.
  - A clip without sound is skipped, and the route answers `{"silent": true}`. Before the stage has run, the route answers 404.
- **Chunk boundaries.** `peaks_stream` reduces whole buckets as audio arrives and carries the remainder, so the result equals one pass (property-tested). The last read of the stream is kept (`stream_stdout(partial_tail=True)`), so the clip's final partial second is included.
- **LUT changes.** The key follows the proxy key, which includes the LUT (ADR 0028). Changing a LUT therefore recomputes the waveform even though the audio is unchanged: cheap and harmless.
- **Caching.** Responses are cached `private, max-age=3600`: derived and keyed by content.
- **Auth.** Every route is behind the session check in server mode (ADR 0034's guards).
- **Frontend.** `lib/time.ts` turns exact `{ticks, tb}` times into seconds for display and for the video element only.
  - **Player keys:** Space toggles; K pauses; L plays, and pressing it again goes 1.5×, 2×, 4×; J jumps back 5 s (HTML video has no reverse play); ←/→ step one frame at the proxy's rate; Shift+←/→ step one second.
  - **Scrub bar:** shows the usable range (`use` tint), moments (`info`), findings (`maybe`) and the accent playhead.

## Consequences

- Existing projects get waveforms at their next analysis; the stage is new and cheap. Until then, clip detail shows no waveform.
- Stories use a small generated clip, `src/stories/assets/sample.mp4`, made by the project's own synthetic generator.
