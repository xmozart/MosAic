# ADR 0006 — Camera profile protocol: per-directory batches and a capture-time hook

- **Status:** accepted (agent decision, M0 step 4)
- **Date:** 2026-10-04

## Context

`MEDIA_SUPPORT.md §1` sketches `CameraProfile` with `detect(probe, path)`,
`group(files)`, `sidecars(file)`, `telemetry(file)`, `color_hint(probe)`,
`proxy_candidate(file)` and `capability(file)`. Implementing the iPhone, GoPro and generic
profiles showed three gaps:

1. Sidecar association needs the whole directory: a GoPro `GL020042.LRF` belongs to
   `GX020042.MP4`, a different name, and the owner may be listed after the sidecar.
2. `proxy_candidate` is a property of the sidecar link, not of the owner alone.
3. Capture time and camera make/model are profile-specific (QuickTime `creationdate` on
   iPhone, a confirmed handler or GPMF track on GoPro), and the spec has no hook for them.

## Options

1. Keep per-file `sidecars(file)` and search the directory inside each call (quadratic).
2. Batch: `sidecars(sidecars, owners)` over one directory, returning links that carry
   `proxy_candidate`; add `capture_time(probe)` and `camera(probe)`.

## Decision

Option 2. The protocol is:

```python
class CameraProfile(Protocol):
    id: str
    def detect(self, probe: ProbeResult | None, path: str) -> float: ...
    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]: ...   # one directory
    def sidecars(self, sidecars, owners) -> list[SidecarLink]: ...          # link.proxy_candidate
    def color_hint(self, probe: ProbeResult) -> str: ...                    # sdr|hlg|pq|log(<name>)
    def capability(self, probe: ProbeResult | None, path: str) -> Capability: ...
    def capture_time(self, probe: ProbeResult) -> str | None: ...
    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]: ...
    # telemetry(file) is added with GPMF (M0 step 8).
```

Each sidecar is offered to every profile in order; the first that finds its owner wins,
so mixed GoPro/DJI/generic folders all link. Grouping runs one directory at a time, which
also bounds memory on large projects (invariant 13).

## Consequences

- `MEDIA_SUPPORT.md §1` is updated to this protocol.
- Chapters split across directories are not grouped; cameras write chapters to one folder.
