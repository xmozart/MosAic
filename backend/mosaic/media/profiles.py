"""Camera profiles (MEDIA_SUPPORT.md §1–2). M0 ships ``iphone``, ``gopro`` and ``generic``.

A profile recognizes its files, groups them into assets (chapters, Live Photo pairs),
associates sidecars and gives color, capability and capture-time hints. Adding a camera
means adding a profile, not changing the pipeline. ``group`` and ``sidecars`` work on one
directory's files at a time (ADR 0006).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import PurePosixPath
from typing import Protocol

from mosaic.media.probe import HFR_THRESHOLD, ProbeResult, StreamInfo
from mosaic.media.scan import MediaType


@dataclass(frozen=True)
class FileRecord:
    """What grouping knows about one probed file."""

    id: int
    rel_path: str
    media_type: MediaType
    probe: ProbeResult | None
    usable: bool  # probed and decodable

    @property
    def name(self) -> str:
        return PurePosixPath(self.rel_path).name

    @property
    def stem(self) -> str:
        return PurePosixPath(self.rel_path).stem

    @property
    def parent(self) -> str:
        return str(PurePosixPath(self.rel_path).parent)


@dataclass
class AssetGroup:
    key: str
    profile: str
    kind: str  # video|photo|live_photo|audio
    files: list[FileRecord]
    status: str = "ok"  # ok|deferred
    reason: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SidecarLink:
    sidecar: FileRecord
    owner: FileRecord | None
    kind: str
    proxy_candidate: bool


@dataclass(frozen=True)
class Capability:
    """``full`` | ``analysis_only`` | ``unsupported`` (with a reason and suggested fix)."""

    level: str
    reason: str | None = None
    fix: str | None = None


FULL = Capability("full")


class CameraProfile(Protocol):
    id: str

    def detect(self, probe: ProbeResult | None, path: str) -> float: ...

    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]: ...

    def sidecars(
        self, sidecars: Sequence[FileRecord], owners: Sequence[FileRecord]
    ) -> list[SidecarLink]: ...

    def color_hint(self, probe: ProbeResult) -> str: ...

    def capability(self, probe: ProbeResult | None, path: str) -> Capability: ...

    def capture_time(self, probe: ProbeResult) -> str | None: ...

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]: ...


# --------------------------------------------------------------------- helpers


def stream_color_hint(stream: StreamInfo | None) -> str:
    if stream is None:
        return "sdr"
    if stream.color_transfer == "arib-std-b67":
        return "hlg"
    if stream.color_transfer == "smpte2084":
        return "pq"
    return "sdr"


def select_audio(probe: ProbeResult) -> StreamInfo | None:
    """Pick the stereo-compatible track (MEDIA_SUPPORT.md §2): stereo AAC first, then any
    stereo track, then the first audio track."""
    audio = probe.audio_streams
    if not audio:
        return None
    for s in audio:
        if s.codec_name == "aac" and (s.channels or 0) == 2:
            return s
    for s in audio:
        if (s.channels or 0) == 2:
            return s
    return audio[0]


def normalize_iso(value: str | None) -> str | None:
    """Normalize QuickTime/ffprobe timestamps to ISO-8601 with an offset."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.isoformat(timespec="seconds")


def is_hfr(stream: StreamInfo | None) -> bool:
    rate = stream.avg_rate or stream.rate if stream else None
    return bool(rate and rate >= HFR_THRESHOLD)


def low_bitrate(probe: ProbeResult, stream: StreamInfo | None) -> bool:
    if stream is None or not probe.bit_rate or not stream.height:
        return False
    return stream.height >= 720 and probe.bit_rate < 2_500_000


def _single(profile: str, rec: FileRecord) -> AssetGroup:
    kind = {MediaType.PHOTO: "photo", MediaType.AUDIO: "audio"}.get(rec.media_type, "video")
    group = AssetGroup(key=f"{profile}:{rec.rel_path}", profile=profile, kind=kind, files=[rec])
    if kind == "photo":
        group.status, group.reason = "deferred", "Photos are analyzed from M1."
    elif kind == "audio":
        group.status = "deferred"
        group.reason = "Standalone audio files are used in a later version."
    return group


_UNSUPPORTED_FORMATS = {
    ".360": (
        "GoPro MAX .360 files are not supported yet.",
        "Export a flat MP4 from GoPro Player.",
    ),
    ".nev": (
        "Nikon N-RAW video cannot be decoded.",
        "Export H.264, HEVC or ProRes from NX Studio or your editor.",
    ),
    ".insv": (
        "Raw Insta360 files arrive in a later version.",
        "Export an MP4 from Insta360 Studio.",
    ),
}


# ------------------------------------------------------------------- profiles


class GenericProfile:
    id = "generic"

    def detect(self, probe: ProbeResult | None, path: str) -> float:
        return 0.1

    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]:
        return [_single(self.id, f) for f in files]

    def sidecars(
        self, sidecars: Sequence[FileRecord], owners: Sequence[FileRecord]
    ) -> list[SidecarLink]:
        by_stem = {(o.parent, o.stem.lower()): o for o in owners}
        out = []
        for sc in sidecars:
            owner = by_stem.get((sc.parent, sc.stem.lower()))
            ext = sc.name.rsplit(".", 1)[-1].lower()
            out.append(SidecarLink(sc, owner, ext, proxy_candidate=ext in ("lrf", "lrv")))
        return out

    def color_hint(self, probe: ProbeResult) -> str:
        v = probe.video_streams
        return stream_color_hint(v[0] if v else None)

    def capability(self, probe: ProbeResult | None, path: str) -> Capability:
        ext = PurePosixPath(path).suffix.lower()
        if ext in _UNSUPPORTED_FORMATS:
            reason, fix = _UNSUPPORTED_FORMATS[ext]
            return Capability("unsupported", reason, fix)
        if probe is not None and not probe.video_streams and not probe.audio_streams:
            return Capability("unsupported", "No playable video or audio stream.", None)
        return FULL

    def capture_time(self, probe: ProbeResult) -> str | None:
        return normalize_iso(probe.tag("creation_time"))

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]:
        return probe.tag("make"), probe.tag("model")


class IPhoneProfile(GenericProfile):
    id = "iphone"

    def detect(self, probe: ProbeResult | None, path: str) -> float:
        if probe and (probe.tag("com.apple.quicktime.make") or "").lower() == "apple":
            return 0.95
        name = PurePosixPath(path).name
        if re.match(r"^IMG_\d{4}", name, re.I) or name.endswith("_iOS.MOV"):
            return 0.5
        return 0.0

    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]:
        """Pair Live Photos: a still and a short MOV with the same name, where the MOV
        carries an Apple content identifier. (Comparing the still's own identifier needs
        photo parsing, which arrives with photos in M1.)"""
        stills = {(f.parent, f.stem.lower()): f for f in files if f.media_type is MediaType.PHOTO}
        used: set[int] = set()
        groups: list[AssetGroup] = []
        for f in files:
            if f.media_type is not MediaType.VIDEO or f.probe is None:
                continue
            still = stills.get((f.parent, f.stem.lower()))
            content_id = f.probe.tag("com.apple.quicktime.content.identifier")
            short = f.probe.duration is not None and f.probe.duration <= 4
            if still is not None and content_id and short:
                groups.append(
                    AssetGroup(
                        key=f"iphone:live:{f.rel_path}",
                        profile=self.id,
                        kind="live_photo",
                        files=[still, f],
                        status="deferred",
                        reason="Live Photos are analyzed from M1.",
                    )
                )
                used |= {still.id, f.id}
        groups += [_single(self.id, f) for f in files if f.id not in used]
        return groups

    def capture_time(self, probe: ProbeResult) -> str | None:
        return normalize_iso(probe.tag("com.apple.quicktime.creationdate")) or super().capture_time(
            probe
        )

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]:
        return probe.tag("com.apple.quicktime.make"), probe.tag("com.apple.quicktime.model")


_GOPRO_NEW = re.compile(r"^G([HXL])(\d{2})(\d{4})$", re.I)  # GX010201: chapter 01, file 0201
_GOPRO_OLD_FIRST = re.compile(r"^GOPR(\d{4})$", re.I)
_GOPRO_OLD_NEXT = re.compile(r"^GP(\d{2})(\d{4})$", re.I)


def gopro_chapter(stem: str) -> tuple[str, int] | None:
    """``(recording key, chapter number)`` for GoPro file names, else None."""
    if m := _GOPRO_NEW.match(stem):
        return f"G{m.group(1).upper()}{m.group(3)}", int(m.group(2))
    if m := _GOPRO_OLD_FIRST.match(stem):
        return f"GOPR{m.group(1)}", 0
    if m := _GOPRO_OLD_NEXT.match(stem):
        return f"GOPR{m.group(2)}", int(m.group(1))
    return None


def _gopro_confirmed(probe: ProbeResult | None) -> bool:
    if probe is None:
        return False
    v = probe.video_streams
    handler = (v[0].handler or "") if v else ""
    return "GoPro" in handler or "gpmd" in {s.codec_tag for s in probe.streams}


class GoProProfile(GenericProfile):
    id = "gopro"

    def detect(self, probe: ProbeResult | None, path: str) -> float:
        if _gopro_confirmed(probe):
            return 0.95
        return 0.6 if gopro_chapter(PurePosixPath(path).stem) is not None else 0.0

    @staticmethod
    def _compatible(a: FileRecord, b: FileRecord) -> bool:
        if a.probe is None or b.probe is None:
            return False
        va, vb = a.probe.video_streams, b.probe.video_streams
        if not va or not vb:
            return False
        x, y = va[0], vb[0]
        return (x.codec_name, x.width, x.height, x.rate) == (
            y.codec_name,
            y.width,
            y.height,
            y.rate,
        )

    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]:
        chapters: dict[tuple[str, str], list[tuple[int, FileRecord]]] = {}
        groups: list[AssetGroup] = []
        for f in files:
            ch = gopro_chapter(f.stem) if f.media_type is MediaType.VIDEO else None
            if ch is None:
                groups.append(_single(self.id, f))
                continue
            chapters.setdefault((f.parent, ch[0]), []).append((ch[1], f))
        for (parent, rec_key), members in sorted(chapters.items()):
            members.sort(key=lambda m: m[0])
            current: list[FileRecord] = [members[0][1]]
            part = 0
            for _, f in members[1:]:
                if self._compatible(current[-1], f):
                    current.append(f)
                else:  # settings changed mid-recording: start a new asset
                    groups.append(self._chaptered(parent, rec_key, part, current))
                    part += 1
                    current = [f]
            groups.append(self._chaptered(parent, rec_key, part, current))
        return groups

    def _chaptered(
        self, parent: str, rec_key: str, part: int, files: list[FileRecord]
    ) -> AssetGroup:
        suffix = f"#{part}" if part else ""
        return AssetGroup(
            key=f"gopro:{parent}/{rec_key}{suffix}", profile=self.id, kind="video", files=files
        )

    def sidecars(
        self, sidecars: Sequence[FileRecord], owners: Sequence[FileRecord]
    ) -> list[SidecarLink]:
        """GoPro LRF ``GLccnnnn`` belongs to ``GXccnnnn``/``GHccnnnn``; files the GoPro
        naming does not explain fall back to the generic same-stem rule."""
        by_chapter: dict[tuple[str, str, int], FileRecord] = {}
        for o in owners:
            ch = gopro_chapter(o.stem)
            if ch:
                by_chapter[(o.parent, ch[0][2:], ch[1])] = o
        fallback = {link.sidecar.id: link for link in super().sidecars(sidecars, owners)}
        out: list[SidecarLink] = []
        for sc in sidecars:
            ext = sc.name.rsplit(".", 1)[-1].lower()
            ch = gopro_chapter(sc.stem)
            owner = by_chapter.get((sc.parent, ch[0][2:], ch[1])) if ch else None
            if owner is None:
                out.append(fallback[sc.id])
            else:
                out.append(SidecarLink(sc, owner, ext, proxy_candidate=ext == "lrf"))
        return out

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]:
        # Only when the file itself says so (invariant 16), never from the name alone.
        return ("GoPro", None) if _gopro_confirmed(probe) else (None, None)


PROFILES: tuple[CameraProfile, ...] = (IPhoneProfile(), GoProProfile(), GenericProfile())


def profile_for(rec: FileRecord) -> CameraProfile:
    """Highest-confidence profile wins; ``generic`` is the fallback."""
    best: CameraProfile = PROFILES[-1]
    best_score = 0.0
    for p in PROFILES:
        score = p.detect(rec.probe, rec.rel_path)
        if score > best_score:
            best, best_score = p, score
    return best


def profile_by_id(pid: str) -> CameraProfile:
    for p in PROFILES:
        if p.id == pid:
            return p
    return PROFILES[-1]


def lrf_matches(owner: ProbeResult, lrf: ProbeResult) -> str | None:
    """Validate a camera proxy against its original. Returns a reason if invalid."""
    ov, lv = owner.video_streams, lrf.video_streams
    if not ov or not lv:
        return "proxy has no video stream"
    if ov[0].rate != lv[0].rate:
        return f"frame rate {lv[0].rate} differs from the original {ov[0].rate}"
    # Compare video stream durations: container durations include audio, whose tail length
    # varies between files of the same recording.
    od, ld = _video_duration(ov[0], owner), _video_duration(lv[0], lrf)
    if od is None or ld is None:
        return "duration unknown"
    one_frame = 1 / ov[0].rate if ov[0].rate else Fraction(1, 30)
    if abs(od - ld) > 2 * one_frame:
        return "duration differs from the original"
    return None


def _video_duration(stream: StreamInfo, probe: ProbeResult) -> Fraction | None:
    if stream.duration_ts is not None:
        return stream.duration_ts * stream.time_base
    return probe.duration
