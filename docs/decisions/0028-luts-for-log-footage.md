# ADR 0028 — LUTs for log footage

- **Status:** accepted (agent decision, M1 step 10b)
- **Date:** 2026-10-05

## Context

M1 scope: "a per-profile color hint. LUT application for log sources, with the
user-supplied LUT path stored per device profile."

ARCHITECTURE.md §10 says that log sources (Apple Log, N-Log, D-Log M, GoPro flat) use a
per-camera-profile LUT, and that the user supplies vendor LUTs unless redistribution is
licensed. Profiles already give `sdr`, `hlg` or `pq` hints, and HLG/PQ are tone-mapped.

Reliable automatic detection of log footage needs real samples of each camera, and none
exist in the corpus yet (Q-3).

## Decision

- **Per device, chosen by the owner.**
  - A device (ADR 0027) can be given a 3D `.cube` LUT through
    `PUT /projects/{pid}/devices` (`{id, lut_path}` or `{id, clear_lut: true}`) or
    `mosaic device FOLDER --lut ID=PATH`.
  - The file is validated: `LUT_3D_SIZE` between 2 and 65, exactly size³ numeric rows,
    no 1D LUTs, at most 64 MB.
  - The LUT is **copied into the artifact store**, keyed by its content (`lut-` plus
    the first 32 hex digits of its SHA-256). It is copied once to a private temp file,
    and that copy is validated, hashed and stored, so the file cannot change between
    the steps. The device is looked up first, and only regular files are accepted. Renders stay reproducible if the original file moves, and
    projects remain portable. The device records both the original path and the key.
- **Applied with FFmpeg `lut3d`** (LGPL, tetrahedral interpolation), in RGB.
  - **Conversion:** the source's YUV is converted explicitly, with its own range
    (limited or full), to full-range 16-bit RGB. Then the LUT runs. The next `scale`
    reads that RGB and produces limited-range Rec.709. An identity LUT leaves the levels
    of limited- and full-range sources unchanged; this is tested with real FFmpeg.
  - **Proxies:** the LUT comes first, before scaling and projection.
  - **Final renders:** it is applied after conforming the frame rate and before scaling.
  - **Previews:** they read proxies, which already carry the LUT. Until the owner
    re-runs the analysis, previews use the existing proxy without the LUT.
  - **The LUT replaces tone mapping.** A log-to-Rec.709 LUT outputs SDR, so an HLG- or
    PQ-tagged source with a LUT is never tone-mapped again.
  - **Path escaping:** FFmpeg unescapes the path twice, once for the filtergraph and
    once for the filter options, so it is escaped for both. A folder named
    `Mike's d:ir, [x]` works.
- **Keys.** Only when a LUT is set, its key is added to the proxy key and to each final
  render chunk's inputs. Assets without a LUT keep their keys. A LUT change therefore
  re-makes that device's proxies and analysis, which is the intended effect. Clearing it
  returns to the original proxy, which is still in the store.
- **Re-analysis is not started automatically.** The response says `reanalysis_needed`
  and the CLI says to run `mosaic analyze`. Re-analysis may include AI calls, so the
  owner starts it.
- **No automatic log detection yet.** The colour hint stays `sdr`, `hlg` or `pq` from the
  stream's tags. When the owner's real Apple Log, N-Log or D-Log M samples arrive (Q-3),
  profile hints can name the curve and suggest assigning a LUT.

## Consequences

- Log footage gets the owner's LUT in analysis frames, contact sheets, previews and final
  renders, and vision judges correctly exposed pictures.
- Vendor LUTs are never shipped, so there is no licensing exposure.
