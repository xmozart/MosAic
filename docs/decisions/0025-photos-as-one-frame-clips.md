# ADR 0025 — Photos: ingest, Live Photos, and analysis as one-frame clips

- **Status:** accepted (agent decision, M1 step 9a)
- **Date:** 2026-10-05

## Context

M1 scope: "HEIC, JPEG, NEF and DNG ingest; Live Photo pairing; burst grouping; photo +
video moment clustering; photos in mosaics and vision." In M0 photos were deferred.

Photos in edits (timeline stills, pan/zoom, blurred fill: MEDIA_SUPPORT.md §3) are not in
M1, but must not be made impossible. Decoders must be licence-clean: pillow-heif's wheels
bundle the GPL x265 encoder.

## Decision

- **Reading** (`media/photo.py`). Originals are opened read-only.
  - **JPEG/PNG/TIFF:** Pillow.
  - **HEIC/HEIF:** pi-heif. It decodes only, and its libheif and libde265 (LGPL-3.0)
    are separate shared libraries; there is no x265 (LICENSES.md).
  - **NEF/NRW/DNG:** the largest **embedded preview JPEG**, found by a minimal TIFF IFD
    walk over IFD0, the IFD chain and SubIFDs. It uses `JPEGInterchangeFormat`, or a
    single JPEG strip that is RGB or YCbCr, never sensor data. The raw's orientation,
    make, model and EXIF capture time come from the same walk. No raw decoder is needed
    for analysis. LibRaw (rawpy, LGPL, dynamic) remains the option for full-quality
    renders later.
  - **Other raws:** ARW and CR2 are TIFF-based too and are read the same way. CR3, RAF,
    ORF and RW2 are unsupported, with "shoot RAW+JPEG or export JPEGs" as the fix.
  - **Hostile or corrupt files:** every count and offset is checked against the file
    size, and the walk is bounded (64 IFDs, 16 SubIFDs, capped value counts). Any failure,
    including decompression bombs, becomes a `PhotoError` with an owner-facing reason
    (invariant 14). Tests cover zero counts, offsets past the end, huge counts, loops,
    huge SubIFD lists and truncation, each within a time bound.
  - **Probing reads no pixels.** Size, EXIF and orientation come from headers, so 20k
    photos probe in bounded memory (invariant 13). Analysis decodes JPEGs scaled down
    (`draft`) to about the 720 px short side.
  - **Orientation:** EXIF orientation is applied, so widths and heights are as displayed.
  - **Capture time:** `DateTimeOriginal` plus `OffsetTimeOriginal`, as ISO 8601 with the
    offset when the camera wrote one. Without an offset the time is the camera's local
    time and stays naive, so code that compares times (for example step 9b moments)
    must never mix naive and offset-aware values.
  - **Apple ContentIdentifier:** read from the EXIF MakerNote (the `Apple iOS` header, a
    big-endian IFD, tag 0x0011).
  - **One probe shape:** a photo is described as an ffprobe-shaped probe (one picture
    "stream", duration 0), with the identifier under the same tag as in a Live Photo MOV.
    Profiles, grouping and capability checks therefore treat photos and videos alike.
- **Live Photos.** A still and a short MOV (≤ 4 s) that carry the same content identifier
  are one `live_photo` asset, whatever their names. A still without a readable identifier
  still pairs by name with a MOV that has one; a still with a *different* identifier
  never does. The still is the asset's analyzed file; the MOV stays with the asset for
  later motion use.
- **Photo assets** have time base `1/1`, duration 0, and one `AssetFile` (the still). Their
  per-asset stages are chosen by kind (`StageDef.kinds`):
  - `photo.analyze` writes a 640 px thumbnail sample, frame metrics measured at proxy
    scale (short side 720, so percentiles compare with video frames), and one shot
    (`method = photo`) at tick 0. Its rows are versioned like `visual` (`asset_stage`).
  - Then `embed`, then `photo.segment`: one segment at tick 0, whose embedding is the
    sample's. It is stored as kind `photo_segment` in its **own vector index**, so photos
    never take video segments' nearest-neighbour slots, and adding photos changes
    nothing in video similarity.
  - Then `mosaics` and `vision`.
  - Range checks that would miss a zero-length segment include its one frame.
- **Dispositions** cover photos and Live Photos. Duration rules (too short, accidental
  recording) do not apply to stills (`dispositions/5`).
- **Not yet:**
  - **Edits:** photos are not edit candidates (retrieval reads video assets only) until
    stills are supported on the timeline.
  - **Video similarity:** photos stay out of video similarity groups, so a photo never
    turns a video segment into a non-recommended look-alike. Bursts and photo + video
    moments get their own grouping (step 9b).
  - **Other stages:** photos are not reviewed by L3 and not in scene summaries yet.
- **Fixtures.**
  - Synthetic JPEGs with EXIF, MakerNotes and orientation.
  - A NEF-shaped TIFF with an embedded preview.
  - A committed 2.5 KB HEIC made with macOS `sips` from a test pattern.
  - The owner's real Nikon and iPhone JPEGs are read correctly, including their offsets.

## Consequences

- Photos now flow through analysis. Each photo is a one-tile sheet and one vision call.
  Estimates include these calls, and the photo count covers Live Photos. At 1,000 photos
  that is 1,000 calls against about 42 for an hour of Balanced video (24 tiles per
  sheet). Packing several photos into a shared sheet is a follow-up that needs its own
  ADR.
- The timeline work for stills (M2+) can use the existing photo segments and their vision
  observations without re-analysis.
