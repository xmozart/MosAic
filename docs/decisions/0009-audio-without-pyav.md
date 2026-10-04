# ADR 0009 — Audio without PyAV; transcription from the proxy's audio

- **Status:** accepted (agent decision, M0 step 7; resolves the PyAV question in ADR 0002)
- **Date:** 2026-10-04

## Context

ADR 0002 asked to verify whether PyAV wheels bundle an LGPL-only FFmpeg. They do not: the
PyAV 19.0.1 macOS arm64 wheel bundles `libx264` and `libx265` (GPL). faster-whisper lists
PyAV as a dependency and imports it at module load, but uses it only in `decode_audio`,
which is skipped when a numpy array is passed to `transcribe`.

Audio for analysis must be on the asset's logical timeline (ARCHITECTURE.md §6): sample 0
is the first video frame, chapters are concatenated, and the audio of a file whose audio
starts before or after its video must stay aligned.

## Options

1. Install PyAV (GPL binaries in the product).
2. Drop faster-whisper and drive CTranslate2 Whisper models directly.
3. Exclude PyAV with a uv dependency override, register a placeholder `av` module before
   importing faster-whisper, and decode audio with MosAic's LGPL FFmpeg.

## Decision

Option 3, as ADR 0002 anticipated:

- `pyproject.toml` `[tool.uv] override-dependencies = ["av; sys_platform == 'never'"]`, so
  PyAV is never installed. `mosaic.audio.av_shim.install()` registers a module that raises
  a clear error if anything tries to use it.
- Audio is decoded from the asset's **proxy**, whose audio track is already aligned to
  logical time 0, concatenated across chapters and pinned to each chapter's video length
  (step 5). Loudness reads 48 kHz stereo; VAD and Whisper read 16 kHz mono, in 10-minute
  blocks with 2 s overlap (words are owned by the block their start falls in).
- Loudness is computed in MosAic (streaming BS.1770 meter) and agrees with FFmpeg's
  `ebur128` within 0.5 LU in the tests.
- Whisper and Silero VAD times (float seconds) become ticks in `mosaic.audio.analysis`,
  the module boundary (ADR 0002 G).

## Interim: direct faster-whisper call until the provider layer (step 9)

`ARCHITECTURE.md §11` puts transcription behind the `Transcriber` capability, with local
faster-whisper as a v1 provider in `ai/adapters/`. That interface and the provider registry
arrive in M0 step 9. Until then `mosaic.audio.analysis` calls faster-whisper directly and
takes the model from `MOSAIC_STT_MODEL` (default `medium`, `small` in tests). Step 9 moves
it behind `Transcriber` in `ai/adapters/faster_whisper/`, with the model chosen from the
analysis mode (Quick small, Balanced medium, Thorough large) and the app settings.

## Consequences

- The proxy's AAC encode (128 kbit/s) is the transcription source. That is adequate for
  speech recognition; final renders still use original audio.
- The installed-library guard (`test_no_bundled_gpl_media_libraries`) would fail if PyAV
  were ever installed.
- `LICENSES.md` lists PyAV as excluded.
