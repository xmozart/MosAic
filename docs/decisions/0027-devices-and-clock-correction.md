# ADR 0027 — Devices and clock correction

- **Status:** accepted (agent decision, M1 step 10a)
- **Date:** 2026-10-05

## Context

MEDIA_SUPPORT.md §4 asks for three things:

- Capture times normalized to an instant plus the original offset.
- A per-device clock offset, keyed by make, model and serial. It is suggested from
  overlapping evidence (a phone photo and a camera clip of the same scene within a
  plausible window), confirmed by the owner, stored in the project DB, and applied
  wherever chronology matters.

S6's acceptance requires that applying offsets regroups days across the Library without
re-analysis. GoPro clocks are often wrong or labelled UTC; the owner's GoPro is an example.

## Decision

- **Devices.** A `device` table (migration `d4e7a90b1c62`). Each video and photo asset
  links to its device, keyed by make, model and serial when the file states them, else
  by camera profile (`profile:gopro`). The device holds `clock_offset_ms` (an integer;
  invariant 3), the offset's source (`none`, `user` or `accepted`), and the LUT path
  (step 10b).
- **Raw and corrected times.**
  - `asset.capture_time_raw` keeps the file's time.
  - `asset.capture_time` is the raw time plus the device's offset, keeping the original
    UTC offset or its absence.
  - Everything that orders or groups by time already reads `capture_time`: trip days,
    the editor's chronology, deepening by day, summaries, captures and estimates. So
    changing an offset rewrites those strings, and day grouping follows immediately.
  - A small job then rebuilds captures and summaries. No analysis stage runs.
- **Suggestions** (`library.clock`, an L1 project stage after `moments`; no AI).
  - **Reference device:** a phone (make Apple: network time) if present, else the device
    with the most assets.
  - **Evidence:** for every other device, up to 200 of its segments, spread over its
    time, are matched by embedding against the video and photo-segment indexes. Hits
    within cosine distance 0.12 that belong to the reference device are evidence pairs.
  - **Neighbours:** each search asks for 64 neighbours, nearest first, and stops at the
    distance bound. That reaches past the device's own look-alike segments to the
    reference's, for video against video as well as video against photos.
  - **Candidate offsets:** each pair gives the reference's *corrected* time (an owner's
    fix to the phone counts) minus the device's raw segment-midpoint time, limited to
    ±48 h. The suggestion is therefore the absolute offset to set.
  - The verdict shown is what is still off after the device's current offset ("on
    time" plus `applied` once accepted). `pairs` counts every agreeing pair, while
    `evidence` keeps the three closest.
  - **Result:** the densest 2-minute cluster with at least 3 pairs gives the suggested
    offset (its median). The 3 closest pairs are kept as evidence (S6 shows a pair).
  - Offsets under 60 s are reported as "on time".
  - Camera-local (naive) and offset-aware times are never compared.
  - **Zone.** An accepted suggestion also adopts the reference's usual UTC offset for
    an offset-aware device. A GoPro that labels local time as UTC then reads in the
    trip's zone, so day boundaries fall at the right midnight. A later hand adjustment
    keeps the adopted zone. Trip-context zones per day remain a later refinement.
  - After any offset change the refresh job also re-runs `library.clock`, so the other
    devices' suggestions follow a fix to the reference.
  - Suggestions are never applied automatically.
- **Interfaces.**
  - `GET /projects/{pid}/devices` and `GET /projects/{pid}/devices/suggestions` (with
    a verdict such as "2 h 00 m behind").
  - `PUT /projects/{pid}/devices`, with `{devices: [{id, clock_offset_ms | accept_suggestion}]}`.
  - The CLI: `mosaic clock FOLDER [--set ID=+5h] [--accept ID]`.

- **Limits.**
  - A phone is recognized by make Apple; Android phones fall back to "most assets".
    A profile flag for network time is a follow-up.
  - `camera_serial` is not read yet, so two bodies of one model share a device.
  - Projects analyzed before this step have no devices until their next scan: the
    group stage creates them (`group/3`). `mosaic clock` says so.

## Consequences

- Clips from a camera with a wrong clock move to the right day and the right place in
  the story once the owner accepts the suggestion. Captures across devices become
  meaningful.
- A device with no visual overlap with the phone gets no suggestion. The owner can still
  set an offset by hand.
- Time zones per trip day (trip context) remain a later refinement, as does GPS-based
  evidence.
