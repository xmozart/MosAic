# Media Support

The commercial goal is "any camera, any length." v1 targets the devices below. Everything is implemented through **camera profiles**, so adding a device means adding a plug-in, not changing the pipeline.

## 1. Camera profile plug-in model

```python
class CameraProfile(Protocol):
    id: str                                   # "gopro", "iphone", "insta360", "nikon_z", "dji", "generic"

    def detect(self, probe: ProbeResult, path: RelPath) -> float: ...
        # confidence 0..1

    def group(self, files: list[MediaFile]) -> list[AssetGroup]: ...
        # chapters, pairs, bursts

    def sidecars(self, file: MediaFile) -> list[Sidecar]: ...
        # LRF, LRV, THM, SRT, XMP...

    def telemetry(self, file: MediaFile) -> Telemetry | None: ...
        # gyro, accel, GPS

    def color_hint(self, probe: ProbeResult) -> ColorHint: ...
        # sdr | hlg | pq | log(<name>)

    def proxy_candidate(self, file: MediaFile) -> MediaFile | None: ...
        # reuse camera proxy

    def capability(self, file: MediaFile) -> SupportLevel: ...
        # full | analysis_only | unsupported(reason)
```

- The highest-confidence profile wins, and `generic` is the fallback.
- Each profile ships with synthetic and real fixture tests.
- Unknown formats become `unsupported` Assets with a human-readable reason and a suggested fix (for example, "Export from Insta360 Studio as MP4").

## 2. v1 device matrix

### iPhone
- **Video:** H.264 and HEVC in MOV; HDR (HLG / Dolby Vision profile 8.4); Apple Log and ProRes on Pro models; Cinematic mode; Action mode.
  - Slo-mo: the file is stored at high frame rate and marked `hfr`. Ramp metadata is not read in v1, so the user or AI can choose real-time or slow motion.
  - Spatial video (MV-HEVC): use the base view only.
- **Audio:** files may contain several audio tracks. Pick the stereo-compatible AAC track. Treat others as unsupported, never as fatal.
- **Photos:** HEIC/JPEG and ProRAW DNG. EXIF orientation is honoured.
- **Live Photos:** the HEIC and MOV are paired by the Apple content identifier into one `live_photo` Asset. The MOV can supply 1–3 s of motion.
- **Metadata:** QuickTime `creationdate` with timezone and ISO 6709 location.

### GoPro
- **Chapters:** `GXccnnnn.MP4` / `GHccnnnn.MP4` share `nnnn` across chapters `cc`, so `GX010201` + `GX020201` are one Asset.
- **Sidecars:** `.LRF` is a camera proxy candidate. `.THM` is ignored.
- **Telemetry:** GPMF gives gyro/accel (the primary shake metric) and GPS.
- **Clock:** the camera clock is often wrong or in UTC, so clock correction (§4) matters most here.
- **Limits:** TimeWarp and timelapse are flagged `timelapse` (no usable audio). GoPro MAX `.360` is `unsupported` in v1.

### Insta360
- **Single-lens / flat modes:** MP4 or INSV with a normal single video stream → `full`.
- **Exports from Insta360 Studio:** flat MP4 → `full`.
- **Raw 360 INSV:** dual-fisheye. Depending on the model, the lenses may be in separate files (paired by name) or combined. Status is `analysis_only` in v1: dual-fisheye frames are converted with FFmpeg `v360` into a fixed forward view for sampling. Editing use requires a later milestone (virtual-camera reframing).
  - Stitching quality from the vendor SDK may require a commercial agreement; record this in `LICENSES.md` before using it.
- **Sidecars:** `.LRV` is a proxy candidate. `.insp` 360 stills are `unsupported` in v1.
- **Telemetry:** gyro where it is parseable. Otherwise fall back to optical flow.

### Nikon (Z series and DSLR)
- **Video:** H.264 and H.265 in MOV/MP4; N-Log (LUT required); HLG.
  - N-RAW (`.NEV`) and ProRes RAW are **`unsupported`** because FFmpeg cannot decode them. Tell the user to export from NX Studio or their NLE.
- **Photos:**
  - NEF raw: use the **embedded preview JPEG** for analysis, which is fast and needs no raw decode. Use LibRaw (via `rawpy`) for final render, with licensing checked.
  - JPEG and HEIF.
- **Metadata:** EXIF DateTimeOriginal plus OffsetTime. GPS only if a GPS unit or phone link was used.

### DJI (drones and action cams, common on trips)
- **Chapters:** split at the size limit; group by sequential numbering plus continuous timestamps.
- **Sidecars:** `.LRF` is a proxy candidate. `.SRT` telemetry gives GPS, altitude and camera settings per frame.
- **Color:** D-Log M and HLG.

### Generic
- Any FFmpeg-decodable video or audio, and any Pillow-decodable image (with `pillow-heif` for HEIC).
- Screen recordings and messaging-app re-encodes are flagged `low_bitrate_source`.

## 3. Photos as first-class assets

- **Analysis:** photos flow through the same sample → mosaic → vision pipeline as a single-frame Segment.
- **Bursts:** photos under 1 s apart with high embedding similarity become one burst group, and the best frame is recommended.
- **Photo + video of the same moment:** clustered by capture time plus embedding similarity, so the editor does not show both unless asked.
- **Timeline use:** a `still` event with a duration (default by pace: 2–5 s) and optional pan/zoom motion. The subject-aware start and end crops come from vision observations.
- **Orientation mismatch:** portrait photos in a 16:9 timeline use a blurred-fill background (default), letterbox, or a crop the user chooses.
- **Photo-only projects** (slideshow) are supported through the same editing pipeline.

## 4. Time and clock correction

- **Normalization:** all capture times become an absolute instant plus the original local offset.
- **Per-device clock offset:** a device is keyed by make, model and serial when available.
  - The offset is suggested automatically from overlapping evidence: a phone photo and GoPro clip of the same scene (high embedding similarity) within a plausible window, or GPS from a device with network time.
  - The user confirms or edits it in one screen.
  - Offsets are stored in the project DB and applied everywhere chronology matters.
- **Day boundaries** use trip-context time zones when provided. Otherwise use each device's recorded offset, and fall back to the phone's offset.

## 5. Scan rules

- **Ignored by default:**
  - the app workspace and hidden/system folders
  - `.THM`, `.LRF` and `.LRV` (sidecars, not assets)
  - `.DS_Store`, `Thumbs.db`, `.AAE` (read later as optional iPhone edit metadata)
- **Include/exclude glob patterns** are user-configurable.
- **Relinking:** detect new, missing and changed files on open. If the fingerprint matches under a different path, offer relink rather than treating the file as new footage.
