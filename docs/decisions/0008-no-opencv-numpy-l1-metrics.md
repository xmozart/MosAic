# ADR 0008 — No OpenCV: shot detection and L1 metrics on numpy/SciPy

- **Status:** accepted (agent decision, M0 step 6)
- **Date:** 2026-10-04

## Context

The stack lists PySceneDetect and OpenCV (headless). PySceneDetect's detectors need OpenCV.
Every macOS arm64 `opencv-python-headless` wheel checked (4.10.0.84, 4.11.0.86, 4.12.0.88,
5.0.0.93) bundles a Homebrew FFmpeg built with `--enable-gpl`, `libx264` and `libx265`,
although the package metadata says Apache-2.0. Shipping it in the Mac desktop app would
distribute GPL binaries, which `CLAUDE.md` forbids without an ADR. The Linux wheel does not
bundle x264/x265, but the Mac app is the first target.

## Options

1. Accept the GPL wheel (would need an owner licensing decision, gate G4).
2. Build OpenCV from source without FFmpeg for dev, CI and packaging.
3. Implement what M0 needs on numpy/SciPy (BSD-3) and decode frames with our own LGPL FFmpeg.

## Decision

Option 3. M0 needs only a handful of image operations:

- **Shots:** a port of PySceneDetect's `AdaptiveDetector` algorithm (BSD-3-Clause,
  © Brandon Castellano; attributed in `LICENSES.md`): per-frame HSV content value on a
  downscaled frame, adaptive ratio against a ±2-frame window, threshold 3.0, minimum content
  value 15, minimum shot length 0.5 s. Long shots are force-split every 60 s.
- **Sharpness:** variance of a discrete Laplacian. **Exposure:** mean luma and clipped
  fractions. **Noise:** Immerkær's fast noise estimate. **Obstruction:** large dark,
  textureless area. **Freeze:** runs of near-zero content change.
- **Shake (no telemetry):** global translation between consecutive frames by phase
  correlation (FFT); jitter is the residual after a 0.5 s moving average.
- **pHash:** 2-D DCT of a 32×32 grayscale frame, 64-bit sign hash.
- **Images:** Pillow for JPEG encoding.

Frames come from the proxy through `media/ffmpeg` builders as streamed raw video.

A test scans installed native libraries for GPL codec libraries, because package
metadata alone did not reveal the problem.

## Consequences

- `CLAUDE.md`'s stack line, `ARCHITECTURE.md §1/§8`, `milestones/M0.md` and
  `ANALYSIS_MODES.md §2` point here. PySceneDetect can come
  back if an LGPL/BSD OpenCV build is ever available; the detector interface is isolated in
  `media/l1.py`.
- Balanced mode also splits shots longer than 60 s (a memory and segment-size safety net);
  Thorough's finer forced subdivision arrives with that mode.
- I-frame samples are not taken: proxies have a fixed GOP, so their keyframes carry no
  editorial signal; scene-change and fixed-interval samples are kept.
