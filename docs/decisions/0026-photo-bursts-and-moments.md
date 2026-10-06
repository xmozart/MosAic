# ADR 0026 — Photo bursts and photo + video moments

- **Status:** accepted (agent decision, M1 step 9b)
- **Date:** 2026-10-05

## Context

MEDIA_SUPPORT.md §3 defines two kinds of group:

- **Bursts:** photos under 1 s apart with high embedding similarity, with the best frame
  recommended.
- **Photo + video of the same moment:** clustered by capture time plus embedding
  similarity, so the editor does not show both unless asked.

Photos are analyzed as one-frame clips (ADR 0025). Their vectors are kept apart from
video similarity on purpose.

## Decision

- **Storage.** A `photo_group` table holds groups of kind `burst` or `capture`, with the
  burst's `best_segment_id`. A `photo_group_member` table holds the segment ids.
  - "Capture" avoids the word *Moment*, which ARCHITECTURE.md §5.2 uses for a point of
    interest inside a segment.
  - This replaces ARCHITECTURE.md's `burst_group`, because one shape serves both
    groupings.
  - Video similarity groups are untouched, so a video segment can be in its look-alike
    group and in a capture.
- **Bursts.**
  - Photos are grouped per camera (make and model). Photos with no make or model share
    one bucket; time and look still decide.
  - Within a camera, photos are in time order, each less than `BURST_GAP` (1 s) after
    the previous one and within cosine distance `BURST_MAX_DISTANCE` (0.15) of it.
    Only runs of two or more photos are bursts.
  - **Best frame:** the highest quality (the same sharpness, shake and clipping score as
    video, from project percentiles), among photos that are not REJECT. If all are
    rejected, all are considered. Ties go to the earliest.
- **Captures.** A photo is grouped with the video segments that meet both conditions:
  - their capture span (the asset's capture time plus the segment's range) overlaps the
    photo's time ±`MOMENT_WINDOW` (10 s);
  - they are within cosine distance `MOMENT_MAX_DISTANCE` (0.2). Different sensors and
    lenses need a looser bound than bursts.

  Photos that share a matched segment are merged into one capture, so a burst near a
  clip makes one group.
- **Time.**
  - Photos keep sub-second capture times (EXIF `SubSecTimeOriginal`, truncated to the
    millisecond, so formatting is idempotent), which bursts need. The photo probe
    version is `photo-probe/2`, so photos analyzed in step 9a are re-read. Times without
    a fraction are formatted as before, so existing video capture times are unchanged.
  - Naive (camera-local) and offset-aware times are never compared.
  - Device clock offsets come with step 10. Until then a camera with a wrong clock finds
    no moments; it never finds wrong ones.
- **Stage.**
  - Bursts were placed in the L0 group stage in ARCHITECTURE.md. They need embeddings
    and dispositions, so they are grouped here instead.
  - `library.moments` is an L1 project stage after dispositions (it needs REJECT for
    the best frame) and before deep review and summaries. It uses no AI.
  - Its key streams every input:
    - segments with their provenance, capture times, devices and status;
    - segment and photo-segment embeddings;
    - photo dispositions;
    - photo metric provenance (quality).
  - Scale:
    - id lists are chunked;
    - quality is computed only for burst members;
    - videos near a photo are found by bisecting the precomputed sorted starts on both
      sides: from `t − window − longest span` to `t + window`;
    - a small cache holds the clips near the photos, which are visited in time order.
  - Photo vectors are held in memory for the run (about 60 MB at 20k photos).
  - A user REJECT on a photo changes the key, so the next run moves the best frame. A
    future USE/REJECT endpoint must enqueue `library.moments`.
  - Deep review is video-only, so the dispositions re-run after L3 never changes a
    photo's input here.
  - Groups are rebuilt whenever an input changes. Purging a segment removes its
    memberships.
- **Thresholds are first estimates** from synthetic fixtures. They are calibrated on the
  owner's corpus like the other thresholds (ADR 0001).

## Consequences

- The library and the editor (M2+) can show one photo per burst and avoid showing a
  photo and its clip together. Nothing changes in edits yet, because photos are not
  edit candidates.
- With device clock correction (step 10), moments across devices become reliable.
