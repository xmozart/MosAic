# ADR 0024 — Camera profiles: Insta360, DJI, Nikon, and an unsupported catalog

- **Status:** accepted (agent decision, M1 step 8)
- **Date:** 2026-10-05

## Context

MEDIA_SUPPORT.md §2 defines profiles for Insta360, DJI and Nikon in addition to the M0
iPhone, GoPro and generic profiles. M1 acceptance 4 asks for a real-footage fixture per
camera that classifies as `full`, `analysis_only` or `unsupported` (with a reason), and
says that GoPro and DJI chapters form single assets and Live Photos pair.

M0 had no `analysis_only` path at all. The owner's corpus has real GoPro and iPhone
video, and Nikon Z5 stills, but no Insta360, DJI or Nikon video.

## Decision

- **Insta360** (`insta360`). Detected by a make tag naming Insta360, the `.insv`, `.insp`
  and `.lrv` extensions, or the `VID_<date>_<time>_<lens>_<seq>` names.
  - Flat files (single-lens modes, Studio exports) are `full`.
  - Raw 360 in `.insv` is **`analysis_only`**, flagged `projection:dfisheye` (both lenses
    side by side in one 2:1 frame) or `projection:fisheye` (one stream per lens, or one
    lens per file).
  - Its proxy is FFmpeg `v360` (an LGPL filter) to a fixed **forward view**.
    - The view is a rectilinear 16:9 window, 100° wide and 67.67° tall, so pixels are
      square: tan(v/2) = tan(50°)·9/16.
    - It assumes a 200° lens. `ih_fov`/`iv_fov` are taken as the per-lens field of view,
      also for `dfisheye`. This is not verified on real footage yet (Q-3).
    - Sampling, vision and dispositions then work as for any clip.
    - The projection and these angles are part of the proxy key, only for such assets.
    - If the FFmpeg build lacks `v360`, the task fails with that reason.
  - A lens pair stored as two files (`_00_` front, `_10_` back): the front lens is the
    analyzed asset. The back lens is a separate deferred asset ("Back lens of a 360
    recording"), which reframing can later merge.
  - The `analysis_only` reason and fix from the catalog are shown on the asset.
  - `LRV_…` previews link to the front lens. For 360 recordings they are never the
    analysis proxy, which needs the original's forward view.
- **`analysis_only` is kept out of edits.** Retrieval skips these assets and counts them
  (`analysis_only`). Editing raw 360 needs virtual-camera reframing, which is a later
  milestone.
- **DJI** (`dji`). Detected by a DJI make tag, a DJI handler name, or `DJI_[<timestamp>_]NNNN`
  names. Chapters split at the size limit and are grouped when all of these hold:
  - the numbers are consecutive;
  - the streams are compatible;
  - the capture time of the next file starts within 2 s of the previous file's end.

  `.LRF` files are proxy candidates (same stem, validated as for GoPro) and `.SRT` files
  link as telemetry sidecars (read later). Capture times have 1 s resolution, within
  the 2 s tolerance. Times with and without a UTC offset are never compared.
- **Nikon** (`nikon_z`). Detected by a make tag naming Nikon, or by the `.nev` / `.nef`
  extensions and `DSC_` names. The camera make and model come only from the file.
  `_DSC` names are shared with Sony, so a name-only match only chooses the profile
  (0.4). It never sets the camera make.
  N-RAW is unsupported. N-Log needs LUTs, which come with the colour work in step 10.
- **GoPro TimeWarp and timelapse.** A GoPro-confirmed recording with no audio stream is
  flagged `timelapse`.
- **Unsupported catalog** (`media/unsupported.py`). One table holds every unsupported
  reason, worded for the owner, with a fix:
  - GoPro `.360`, Nikon N-RAW, Insta360 `.insp`, ProRes RAW, Blackmagic RAW, RED;
  - no playable stream; not media.

  Profiles and the probe stage take their messages from it. `.braw` and `.r3d` are now
  recognized as video, so they are listed with a reason instead of "not media".
- **Fixtures.**
  - Synthetic stand-ins (`CorpusGenerator.generate(only={"cameras"})`, opt-in so the
    shared corpus is unchanged) reproduce these cameras' names, tags and stream layouts:
    a flat Insta360 export, dual-fisheye, two-stream and two-file 360, DJI chapters with
    a time gap, LRF and SRT, a Nikon MOV and NEV, a GoPro TimeWarp, and a BRAW file.
  - Real footage is classified read-only from `Samples/` (GoPro, iPhone).
  - Real Insta360, DJI and Nikon video are requested from the owner (OPEN_QUESTIONS
    Q-3).

- **Reclassification.** `PROBE_VERSION` is now `probe/2` and `GROUP_VERSION` is
  `group/2`. A file recorded as unsupported under an older probe key is probed again, so
  existing projects pick up the new profiles: `.insv` becomes analysis_only, and DJI
  chapters are grouped. Analysis keys do not include probe keys, so only probing re-runs: one ffprobe, decode check and VFR packet scan per file, once per existing project.

## Consequences

- Every v1 camera has a profile, and unknown or raw formats always show a reason and a
  fix (invariant 14).
- Classification of real Insta360, DJI and Nikon video is unverified until the owner's
  samples arrive. The profiles accept either tag-based or name-based evidence, to be
  tolerant meanwhile.
