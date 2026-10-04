# Later Milestones (outline, to be detailed when reached)

## M5 — Audio intelligence and mix
- Audio event detection: laughter, cheering, wildlife, water, wind, crowd, traffic. Use a permissively licensed model.
- Speech intelligibility and wind scoring.
- Preservation of natural-sound moments.
- Dialogue-first mix rules.
- Diarization if a license-clean option exists.
- Loudness QC report.

## M6 — Music intelligence
- User music library.
- BPM, beat grid, downbeats, sections and energy curve. Check model licenses: several popular ones are non-commercial.
- Cut alignment modes: ignore, light, major phrases (default), or strong.
- Music-aware beat durations in the solver.
- Ducking with attack/release.
- Warning about Content ID for commercial tracks.
- Future: licensed catalog and generated music.

## M7 — AI review of the rendered cut
- Multimodal review of sampled preview frames plus the audio transcript, for issues the EDL cannot show (visual continuity, color jumps, awkward framing).
- Bounded revision passes (default 1).
- Child versions.

## M8 — Timeline editor and reframing
- Simplified timeline: video, audio and music tracks, thumbnails, waveforms, trim handles, reorder, alternate-shot picker, per-event audio and transition settings, and beat markers.
- Smart reframing for vertical output (subject tracking and a smoothed crop path).
- Insta360 raw 360 editing via virtual-camera keyframes.
- Stabilization recommendations and optional stabilization.
- Color matching between cameras.

## M9 — Windows desktop
- Tauri Windows build, Credential Manager via `keyring`, NVENC/QSV/AMF, long-path handling, and a signed MSI.

## M10 — NLE interchange
- OTIO export, FCPXML export (with schema presets), frame-accuracy validation against the canonical timeline, round-trip tests with Final Cut Pro and DaVinci Resolve, and compatibility reporting.
- Relink package (timeline plus proxies, or plus copied originals).

## M11 — Natural-language editing
- Conversational commands mapped to structured edit operations, such as "make the first minute faster" or "more shots of the kids." Each creates a version.

## M12 — HDR output
- HLG/PQ delivery pipeline and HDR-aware preview.
