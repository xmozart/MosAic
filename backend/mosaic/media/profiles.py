"""Camera profiles (MEDIA_SUPPORT.md §1–2): ``iphone``, ``gopro``, ``insta360``, ``dji``,
``nikon_z`` and ``generic`` (ADR 0024).

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
from mosaic.media.unsupported import CATALOG, unsupported_by_extension


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
    fix: str | None = None  # suggested fix shown with ``reason``


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
        known = unsupported_by_extension(path)
        if known is not None:
            return Capability("unsupported", known.reason, known.fix)
        if probe is not None and not probe.video_streams and not probe.audio_streams:
            entry = CATALOG["no_stream"]
            return Capability("unsupported", entry.reason, entry.fix)
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
        first = files[0].probe
        # TimeWarp and timelapse recordings have no sound (MEDIA_SUPPORT.md §2).
        flags = (
            ["timelapse"] if _gopro_confirmed(first) and first and not first.audio_streams else []
        )
        return AssetGroup(
            key=f"gopro:{parent}/{rec_key}{suffix}",
            profile=self.id,
            kind="video",
            files=files,
            flags=flags,
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


# ------------------------------------------------------------------- Insta360

_INSTA_NAME = re.compile(r"^(VID|LRV|IMG)_(\d{8}_\d{6})_(\d{2})_(\d{3})$", re.I)


def _maker(probe: ProbeResult | None) -> str:
    if probe is None:
        return ""
    return " ".join(
        v
        for v in (probe.tag("make"), probe.tag("com.apple.quicktime.make"), probe.tag("encoder"))
        if v
    ).lower()


def insta_projection(probe: ProbeResult | None, path: str) -> str | None:
    """``dfisheye`` (both lenses side by side in one frame), ``fisheye`` (one lens per
    stream or file), or None for flat footage (single-lens modes, Studio exports)."""
    ext = PurePosixPath(path).suffix.lower()
    if probe is None or ext != ".insv":
        return None
    video = [v for v in probe.video_streams if not v.attached_pic]
    if len(video) >= 2:
        return "fisheye"  # one lens per stream: the front lens (first stream) is used
    if video and video[0].width and video[0].height:
        if video[0].width == 2 * video[0].height:
            return "dfisheye"
        if video[0].width == video[0].height:
            return "fisheye"  # one lens of a pair stored as two files
    return None


class Insta360Profile(GenericProfile):
    id = "insta360"

    def detect(self, probe: ProbeResult | None, path: str) -> float:
        if "insta360" in _maker(probe):
            return 0.95
        p = PurePosixPath(path)
        if p.suffix.lower() in (".insv", ".insp", ".lrv"):
            return 0.9
        # 0.55: ``IMG_<date>_<time>_<lens>_<seq>`` also starts like an iPhone name (0.5).
        return 0.55 if _INSTA_NAME.match(p.stem) else 0.0

    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]:
        """Flat files are single assets. Raw 360 is ``analysis_only`` (ADR 0024): sampled
        through a fixed forward view, never placed in an edit. A pair of lens files
        (``_00_`` front, ``_10_`` back) is one recording: the front lens is analyzed and
        the back lens is kept as part of it, not analyzed separately."""
        groups: list[AssetGroup] = []
        names = {(f.parent, f.stem.lower()): f for f in files}
        for f in files:
            m = _INSTA_NAME.match(f.stem)
            if m and m.group(3) == "10" and f.media_type is MediaType.VIDEO:
                front = names.get((f.parent, f"{m.group(1)}_{m.group(2)}_00_{m.group(4)}".lower()))
                if front is not None:
                    groups.append(
                        AssetGroup(
                            key=f"insta360:back:{f.rel_path}",
                            profile=self.id,
                            kind="video",
                            files=[f],
                            status="deferred",
                            reason="Back lens of a 360 recording; the front lens is analyzed.",
                        )
                    )
                    continue
            group = _single(self.id, f)
            projection = insta_projection(f.probe, f.rel_path)
            if projection and group.kind == "video":
                group.flags = ["analysis_only", f"projection:{projection}"]
                entry = CATALOG["insta360_raw_360"]
                group.reason, group.fix = entry.reason, entry.fix
            groups.append(group)
        return groups

    def sidecars(
        self, sidecars: Sequence[FileRecord], owners: Sequence[FileRecord]
    ) -> list[SidecarLink]:
        """``LRV_<date>_<time>_<nn>_<seq>`` previews belong to the front-lens
        ``VID_<date>_<time>_00_<seq>``. A 360 recording's preview is never its proxy: the
        analysis needs the forward view of the original."""
        owner_by_take: dict[tuple[str, str, str], FileRecord] = {}
        for o in owners:
            m = _INSTA_NAME.match(o.stem)
            if m and m.group(1).upper() == "VID" and m.group(3) == "00":
                owner_by_take[(o.parent, m.group(2), m.group(4))] = o
        fallback = {link.sidecar.id: link for link in super().sidecars(sidecars, owners)}
        out: list[SidecarLink] = []
        for sc in sidecars:
            ext = sc.name.rsplit(".", 1)[-1].lower()
            m = _INSTA_NAME.match(sc.stem)
            owner = owner_by_take.get((sc.parent, m.group(2), m.group(4))) if m else None
            link = (
                SidecarLink(sc, owner, ext, proxy_candidate=ext == "lrv")
                if owner is not None
                else fallback[sc.id]
            )
            if link.owner is not None and insta_projection(link.owner.probe, link.owner.rel_path):
                link = SidecarLink(sc, link.owner, ext, proxy_candidate=False)
            out.append(link)
        return out

    def capability(self, probe: ProbeResult | None, path: str) -> Capability:
        base = super().capability(probe, path)
        if base.level != "full":
            return base
        if insta_projection(probe, path):
            entry = CATALOG["insta360_raw_360"]
            return Capability("analysis_only", entry.reason, entry.fix)
        return FULL

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]:
        return ("Insta360", probe.tag("model")) if "insta360" in _maker(probe) else (None, None)


# ------------------------------------------------------------------------ DJI

_DJI_NAME = re.compile(r"^DJI_(?:(\d{14})_)?(\d{4})(?:_[A-Z])?$", re.I)
CHAPTER_GAP_S = Fraction(2)  # a next chapter starts within this of the previous one's end


def dji_number(stem: str) -> int | None:
    m = _DJI_NAME.match(stem)
    return int(m.group(2)) if m else None


class DJIProfile(GenericProfile):
    id = "dji"

    def detect(self, probe: ProbeResult | None, path: str) -> float:
        if "dji" in _maker(probe):
            return 0.95
        v = probe.video_streams if probe else []
        if v and "DJI" in (v[0].handler or ""):
            return 0.9
        return 0.6 if dji_number(PurePosixPath(path).stem) is not None else 0.0

    def group(self, files: Sequence[FileRecord]) -> list[AssetGroup]:
        """Chapters split at the size limit: consecutive numbers with compatible streams
        whose capture times continue (the next starts where the previous ends)."""
        numbered = sorted(
            (
                (dji_number(f.stem), f)
                for f in files
                if f.media_type is MediaType.VIDEO and dji_number(f.stem) is not None
            ),
            key=lambda t: (t[1].parent, t[0] or 0),
        )
        used: set[int] = set()
        groups: list[AssetGroup] = []
        run: list[tuple[int, FileRecord]] = []

        def flush() -> None:
            if run:
                first = run[0][1]
                groups.append(
                    AssetGroup(
                        key=f"dji:{first.rel_path}",
                        profile=self.id,
                        kind="video",
                        files=[f for _, f in run],
                    )
                )
                used.update(f.id for _, f in run)
                run.clear()

        for n, f in numbered:
            assert n is not None
            if run and not (
                run[-1][1].parent == f.parent
                and n == run[-1][0] + 1
                and GoProProfile._compatible(run[-1][1], f)
                and self._continues(run[-1][1], f)
            ):
                flush()
            run.append((n, f))
        flush()
        groups += [_single(self.id, f) for f in files if f.id not in used]
        return groups

    def _continues(self, a: FileRecord, b: FileRecord) -> bool:
        if a.probe is None or b.probe is None or a.probe.duration is None:
            return False
        ta, tb = self.capture_time(a.probe), self.capture_time(b.probe)
        if ta is None or tb is None:
            return False
        start_a, start_b = datetime.fromisoformat(ta), datetime.fromisoformat(tb)
        if (start_a.tzinfo is None) != (start_b.tzinfo is None):
            return False  # one with an offset, one without: not comparable
        # Capture times have 1 s resolution, inside the 2 s tolerance.
        gap = Fraction((start_b - start_a).total_seconds()) - a.probe.duration
        return abs(gap) <= CHAPTER_GAP_S

    def sidecars(
        self, sidecars: Sequence[FileRecord], owners: Sequence[FileRecord]
    ) -> list[SidecarLink]:
        """``.LRF`` camera proxies and ``.SRT`` telemetry share the clip's stem."""
        return super().sidecars(sidecars, owners)

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]:
        return ("DJI", probe.tag("model")) if "dji" in _maker(probe) else (None, None)


# --------------------------------------------------------------------- Nikon

_NIKON_NAME = re.compile(r"^_?DSC[N_]?\d{4}$", re.I)


class NikonProfile(GenericProfile):
    id = "nikon_z"

    def detect(self, probe: ProbeResult | None, path: str) -> float:
        if "nikon" in _maker(probe):
            return 0.95
        p = PurePosixPath(path)
        if p.suffix.lower() in (".nev", ".nef"):
            return 0.9
        return 0.4 if _NIKON_NAME.match(p.stem) else 0.0

    def camera(self, probe: ProbeResult) -> tuple[str | None, str | None]:
        if "nikon" not in _maker(probe):
            return None, None
        return probe.tag("make"), probe.tag("model")


PROFILES: tuple[CameraProfile, ...] = (
    IPhoneProfile(),
    GoProProfile(),
    Insta360Profile(),
    DJIProfile(),
    NikonProfile(),
    GenericProfile(),
)


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
