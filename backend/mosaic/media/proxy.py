"""Proxies (ARCHITECTURE.md §8 stage 3): 720p H.264 8-bit SDR Rec.709 CFR, plus a tick map.

Quick mode (ANALYSIS_MODES.md §2) proxies at 540p, and transcodes from the camera's own
low-resolution files (GoPro LRF, Insta360 LRV) when every chapter has a valid one. A valid
camera proxy has the original's frame rate and duration (``profiles.lrf_matches``), so its
frame ``i`` is the original's frame ``i`` and the tick map stays in the original's logical
ticks (ADR 0020).

A proxy covers an asset's whole logical timeline (chapters concatenated). Proxy frame
``i`` is the source frame nearest to logical time ``i / proxy_rate`` (``setpts=PTS-STARTPTS``
then the ``fps`` filter, which resamples by PTS, so VFR sources are handled). The tick map
turns proxy frames back into the source frame's logical ticks (ARCHITECTURE.md §6):

- CFR sources: a verified affine map, ``ticks = round(i / proxy_rate / tb)``;
- VFR sources, or CFR sources that fail verification: a table of the logical source
  ticks of the frame each proxy frame shows.

Analysis results are always written in source ticks (invariant 4); callers use
``proxy_frame_to_source_ticks``, never their own arithmetic.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import select

from mosaic.core.keys import artifact_key
from mosaic.core.modes import PRESETS, ModeConfig, task_mode
from mosaic.core.time import Rounding, format_rational, parse_rational, round_fraction
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, task
from mosaic.media import inventory
from mosaic.media import probe as probing
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import FFmpegError, run
from mosaic.media.tools import media_tools, working_h264_encoders
from mosaic.storage import provenance
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    Device,
    MediaFile,
    MediaStream,
    Sidecar,
)
from mosaic.storage.projects import Project

PROXY_VERSION = "proxy/1"
PROXY_SHORT_SIDE = 720
QUICK_SHORT_SIDE = 540
CAMERA_PROXY_KINDS = ("lrf", "lrv")
_QUICK = PRESETS["quick"]
PROXY_MAX_RATE = Fraction(30)
PROXY_BITRATE = "3M"
QUICK_BITRATE = "2M"


def proxy_rate(source_rate: Fraction | None) -> Fraction:
    """Source rate, halved until ≤ 30 fps (59.94 → 29.97, 120 → 30); 30 when unknown."""
    rate = source_rate or PROXY_MAX_RATE
    while rate > PROXY_MAX_RATE + Fraction(1, 1000):
        rate /= 2
    return rate


def proxy_size(
    display_w: int, display_h: int, short_side: int = PROXY_SHORT_SIDE
) -> tuple[int, int]:
    """Short side 720 (or ``short_side``; never upscaled), even dimensions, aspect kept."""
    short = min(display_w, display_h)
    target = min(short_side, short)
    scale = Fraction(target, short)

    def even(x: Fraction) -> int:
        return max(2, 2 * round_fraction(x / 2, Rounding.NEAREST))

    return even(display_w * scale), even(display_h * scale)


@dataclass(frozen=True)
class ChapterInfo:
    rel_path: str
    fingerprint: str
    video_index: int
    tb: Fraction
    start_pts: int
    logical_start_ticks: int  # asset tb
    duration_ticks: int  # asset tb
    nb_frames: int | None


@dataclass(frozen=True)
class ProxyPlan:
    asset_id: int
    chapters: list[ChapterInfo]
    video_index: int
    audio_index: int | None
    color_hint: str
    color_range: str | None
    width: int
    height: int
    source_rate: Fraction | None
    rate: Fraction
    tb: Fraction
    duration_ticks: int
    vfr: bool
    source: str = "original"  # original | camera (the chapters are LRF/LRV sidecars)
    bitrate: str = PROXY_BITRATE
    projection: str | None = None  # 360 footage: a forward view (ADR 0024)
    lut_key: str | None = None  # the device's LUT for log footage (ADR 0028)

    @property
    def fingerprints(self) -> list[str]:
        return [c.fingerprint for c in self.chapters]

    def key(self, project_id: str, encoder: str) -> str:
        # The FFmpeg version is recorded in provenance but not in the key: a rebuilt
        # FFmpeg produces an equivalent proxy, so existing proxies stay valid.
        return artifact_key(
            "proxy",
            project_id=project_id,
            inputs={"files": self.fingerprints, "v": self.video_index, "a": self.audio_index}
            # Only camera-proxy plans carry a source, so 720p keys are unchanged from M0.
            | ({"source": self.source} if self.source != "original" else {})
            | (
                {
                    "projection": self.projection,
                    "fov": [builders.LENS_FOV, builders.FORWARD_HFOV, builders.FORWARD_VFOV],
                }
                if self.projection
                else {}
            )
            | ({"lut": self.lut_key} if self.lut_key else {}),
            config={
                "w": self.width,
                "h": self.height,
                "rate": self.rate,
                "color": self.color_hint,
                "range": self.color_range,
                "encoder": encoder,
                "bitrate": self.bitrate,
            },
            version=PROXY_VERSION,
        )


def plan_for(project: Project, asset_id: int, mode: ModeConfig | None = None) -> ProxyPlan:
    """The proxy of an asset for a mode (Balanced's 720p when no mode is given)."""
    quick = mode is not None and mode.proxy == "lrf_or_540"
    short_side = QUICK_SHORT_SIDE if quick else PROXY_SHORT_SIDE
    with project.db.session() as s:
        asset = s.get(Asset, asset_id)
        if asset is None or asset.tb is None or asset.video_stream_index is None:
            raise PermanentError(f"asset {asset_id} has no video to proxy")
        rows = list(
            s.execute(
                select(AssetFile, MediaFile.rel_path, MediaFile.fingerprint)
                .join(MediaFile, MediaFile.id == AssetFile.media_file_id)
                .where(AssetFile.asset_id == asset_id)
                .order_by(AssetFile.order)
            )
        )
        streams = {
            st.media_file_id: st
            for st in s.scalars(
                select(MediaStream).where(
                    MediaStream.media_file_id.in_([r.AssetFile.media_file_id for r in rows]),
                    MediaStream.stream_index == asset.video_stream_index,
                )
            )
        }
        missing = [r.rel_path for r in rows if r.AssetFile.media_file_id not in streams]
        if not rows or missing:
            raise PermanentError(f"asset {asset_id}: no video stream in {missing or 'files'}")
        source_rate = parse_rational(asset.rate) if asset.rate else None
        lut = (
            s.scalar(select(Device.lut_key).where(Device.id == asset.device_id))
            if asset.device_id is not None
            else None
        )
        common: dict[str, Any] = {
            "lut_key": lut,
            "asset_id": asset_id,
            "source_rate": source_rate,
            "rate": proxy_rate(source_rate),
            "tb": parse_rational(asset.tb),
            "duration_ticks": asset.duration_ticks or 0,
            "vfr": asset.vfr,
            "bitrate": QUICK_BITRATE if quick else PROXY_BITRATE,
        }
        projection = next(
            (f.split(":", 1)[1] for f in (asset.flags or []) if f.startswith("projection:")),
            None,
        )
        if projection:
            # A 360 recording: the forward view is 16:9 whatever the sensor layout, at the
            # usual proxy size (it may upscale a small lens; these assets are only analyzed,
            # never rendered into an edit).
            w, h = proxy_size(1920, 1080, short_side)
            return _flat_plan(s, rows, streams, asset, common, w, h, projection)
        if quick:
            camera = _camera_plan(s, rows, short_side, common, asset.audio_stream_index is not None)
            if camera is not None:
                return camera
        chapters = _chapters(rows, streams)
        first = streams[rows[0].AssetFile.media_file_id]
        w, h = proxy_size(
            asset.display_width or first.width or 1280,
            asset.display_height or first.height or 720,
            short_side,
        )
        return ProxyPlan(
            chapters=chapters,
            video_index=asset.video_stream_index,
            audio_index=asset.audio_stream_index,
            color_hint=asset.color_hint,
            color_range=first.color_range,
            width=w,
            height=h,
            **common,
        )


def _flat_plan(
    s: Any,
    rows: list[Any],
    streams: dict[int, MediaStream],
    asset: Asset,
    common: dict[str, Any],
    w: int,
    h: int,
    projection: str,
) -> ProxyPlan:
    first = streams[rows[0].AssetFile.media_file_id]
    return ProxyPlan(
        chapters=_chapters(rows, streams),
        video_index=asset.video_stream_index or 0,
        audio_index=asset.audio_stream_index,
        color_hint=asset.color_hint,
        color_range=first.color_range,
        width=w,
        height=h,
        projection=projection,
        **common,
    )


def _chapters(rows: list[Any], streams: dict[int, MediaStream]) -> list[ChapterInfo]:
    out = []
    for r in rows:
        st = streams[r.AssetFile.media_file_id]
        out.append(
            ChapterInfo(
                rel_path=r.rel_path,
                fingerprint=r.fingerprint,
                video_index=st.stream_index,
                tb=parse_rational(st.time_base),
                start_pts=st.start_pts,
                logical_start_ticks=r.AssetFile.logical_start_ticks,
                duration_ticks=r.AssetFile.duration_ticks,
                nb_frames=st.nb_frames,
            )
        )
    return out


def _camera_plan(
    s: Any, rows: list[Any], short_side: int, common: dict[str, Any], has_audio: bool
) -> ProxyPlan | None:
    """A plan over the camera's own proxies, if every chapter has a valid one (same
    stream layout in all of them, with sound when the original has it); otherwise None
    and the originals are transcoded."""
    owners = [r.AssetFile.media_file_id for r in rows]
    found: dict[int, tuple[MediaFile, list[MediaStream]]] = {}
    for sc, mf in s.execute(
        select(Sidecar, MediaFile)
        .join(MediaFile, MediaFile.id == Sidecar.media_file_id)
        .where(
            Sidecar.owner_media_file_id.in_(owners),
            Sidecar.kind.in_(CAMERA_PROXY_KINDS),
            Sidecar.status == "valid",
            Sidecar.proxy_candidate.is_(True),
        )
        .order_by(Sidecar.id)
    ):
        if sc.owner_media_file_id in found:
            continue
        sts = list(
            s.scalars(
                select(MediaStream)
                .where(MediaStream.media_file_id == mf.id)
                .order_by(MediaStream.stream_index)
            )
        )
        found[sc.owner_media_file_id] = (mf, sts)
    if set(found) != set(owners):
        return None
    chapters = []
    layout: set[tuple[int, int | None]] = set()
    first_video: MediaStream | None = None
    for r in rows:
        mf, sts = found[r.AssetFile.media_file_id]
        video = next((x for x in sts if x.codec_type == "video"), None)
        audio = next((x for x in sts if x.codec_type == "audio"), None)
        if video is None or video.time_base is None:
            return None
        if has_audio and audio is None:
            return None  # transcription and loudness need the sound
        first_video = first_video or video
        layout.add((video.stream_index, audio.stream_index if audio else None))
        chapters.append(
            ChapterInfo(
                rel_path=mf.rel_path,
                fingerprint=mf.fingerprint,
                video_index=video.stream_index,
                tb=parse_rational(video.time_base),
                start_pts=video.start_pts,
                # The camera proxy is frame-aligned with its original (validated), so it
                # covers the original chapter's logical span.
                logical_start_ticks=r.AssetFile.logical_start_ticks,
                duration_ticks=r.AssetFile.duration_ticks,
                nb_frames=video.nb_frames,
            )
        )
    if len(layout) != 1 or first_video is None:
        return None
    ((video_index, audio_index),) = layout
    w, h = proxy_size(first_video.width or 640, first_video.height or 360, short_side)
    return ProxyPlan(
        chapters=chapters,
        video_index=video_index,
        audio_index=audio_index,
        color_hint="sdr",  # camera proxies are 8-bit SDR H.264
        color_range=first_video.color_range,
        width=w,
        height=h,
        source="camera",
        **common,
    )


# -------------------------------------------------------------------- tick map


def proxy_frame_to_ticks(frame: int, proxy_rate_: Fraction, tb: Fraction) -> int:
    return round_fraction(Fraction(frame) / proxy_rate_ / tb, Rounding.NEAREST)


def ticks_to_proxy_frame(ticks: int, proxy_rate_: Fraction, tb: Fraction) -> int:
    return round_fraction(ticks * tb * proxy_rate_, Rounding.FLOOR)


def cfr_verified(plan: ProxyPlan) -> bool:
    """Trust the affine map only if every chapter's frame count matches duration × rate."""
    if plan.vfr or plan.source_rate is None:
        return False
    for c in plan.chapters:
        if c.nb_frames is None:
            return False
        if abs(Fraction(c.nb_frames) - c.duration_ticks * plan.tb * plan.source_rate) > 2:
            return False
    return True


def parse_pts_lines(stdout: bytes) -> list[int]:
    out = []
    for token in stdout.decode(errors="replace").split():
        token = token.strip().rstrip(",")
        if token.lstrip("-").isdigit():
            out.append(int(token))
    return sorted(out)


def source_frame_ticks(binaries: FFmpegBinaries, root: Path, plan: ProxyPlan) -> list[int]:
    """Logical ticks (asset tb) of every source frame, sorted, across chapters."""
    out: list[int] = []
    for c in plan.chapters:
        res = run(
            binaries, builders.ffprobe_video_pts(root / c.rel_path, c.video_index), timeout=600
        )
        out += [
            c.logical_start_ticks
            + round_fraction((p - c.start_pts) * c.tb / plan.tb, Rounding.NEAREST)
            for p in parse_pts_lines(res.stdout)
            if p >= c.start_pts  # edit-list pre-roll packets are never displayed
        ]
    return sorted(out)


def build_tick_map(plan: ProxyPlan, frames: int, frame_ticks: list[int] | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "proxy_rate": format_rational(plan.rate),
        "tb": format_rational(plan.tb),
        "frames": frames,
        "source_duration_ticks": plan.duration_ticks,
        "vfr": plan.vfr,
    }
    if frame_ticks is None:
        return {**base, "kind": "affine", "verified": True}
    if not frame_ticks:
        raise PermanentError(f"asset {plan.asset_id}: no source frame timestamps")
    table = []
    for i in range(frames):
        t = proxy_frame_to_ticks(i, plan.rate, plan.tb)
        k = bisect.bisect_left(frame_ticks, t)
        cands = [c for c in (k - 1, k) if 0 <= c < len(frame_ticks)]
        best = min(cands, key=lambda c: (abs(frame_ticks[c] - t), c))
        table.append(frame_ticks[best])
    return {**base, "kind": "table", "ticks": table}


def proxy_frame_to_source_ticks(tmap: dict[str, Any], frame: int) -> int:
    """Logical source ticks (asset tb) of the source frame shown by proxy ``frame``."""
    frame = max(0, min(frame, int(tmap["frames"]) - 1))
    if tmap["kind"] == "table":
        return int(tmap["ticks"][frame])
    return proxy_frame_to_ticks(
        frame, parse_rational(tmap["proxy_rate"]), parse_rational(tmap["tb"])
    )


# ----------------------------------------------------------------------- task


def _encoder() -> str:
    encoders = working_h264_encoders()
    if not encoders:
        raise PermanentError(
            "no working H.264 encoder: this FFmpeg build has none that runs on this machine"
        )
    return encoders[0]


def proxy_key(project: Project, asset_id: int, mode: ModeConfig | None = None) -> str:
    """The proxy artifact key for an asset's current files and settings."""
    return plan_for(project, asset_id, mode).key(project.id, _encoder())


@dataclass(frozen=True)
class ProxyInfo:
    key: str
    path: Path
    rate: Fraction
    tb: Fraction
    frames: int
    width: int
    height: int
    tickmap: dict[str, Any]


def load_proxy(project: Project, asset_id: int, mode: ModeConfig | None = None) -> ProxyInfo:
    """The finished proxy of an asset. Analysis stages pass their job's mode; other
    callers (previews) take whichever proxy exists, preferring Balanced's 720p."""
    if mode is not None:
        plan = plan_for(project, asset_id, mode)
    else:
        plans = [plan_for(project, asset_id), plan_for(project, asset_id, _QUICK)]
        # A LUT set since the last analysis: its proxies are not made yet, so previews use
        # the proxies without it until the owner re-runs the analysis (ADR 0028).
        plans += [replace(p, lut_key=None) for p in plans if p.lut_key]
        plan = next(
            (
                p
                for p in plans
                if project.artifacts.exists("tickmap", f"{p.key(project.id, _encoder())}-map")
            ),
            plans[0],
        )
    key = plan.key(project.id, _encoder())
    tmap = project.artifacts.get_json("tickmap", f"{key}-map")
    return ProxyInfo(
        key=key,
        path=project.artifacts.path("proxy", key),
        rate=parse_rational(tmap["proxy_rate"]),
        tb=parse_rational(tmap["tb"]),
        frames=int(tmap["frames"]),
        width=plan.width,
        height=plan.height,
        tickmap=tmap,
    )


def _is_done(ctx: TaskContext) -> bool:
    key = proxy_key(ctx.project, ctx.params["asset_id"], task_mode(ctx))
    store = ctx.project.artifacts
    return store.exists("proxy", key) and store.exists("tickmap", f"{key}-map")


@task("media.proxy", is_done=_is_done)
def proxy_task(ctx: TaskContext) -> dict[str, Any]:
    binaries, caps = media_tools()
    plan = plan_for(ctx.project, ctx.params["asset_id"], task_mode(ctx))
    encoder = _encoder()
    hdr = plan.color_hint if plan.color_hint in ("hlg", "pq") else None
    if plan.lut_key:
        hdr = None  # the LUT replaces tone mapping: its output is SDR Rec.709 (ADR 0028)
    if plan.projection and not caps.has_filter("v360"):
        raise PermanentError("360 footage needs the v360 filter; this FFmpeg build lacks it")
    if hdr and not caps.can_tonemap:
        raise PermanentError("HDR source needs zscale + tonemap; this FFmpeg build lacks them")
    # TODO(log profiles): a "log(<name>)" color hint needs a per-camera LUT
    # (ARCHITECTURE.md §10); no M0 profile emits it, so log sources take the SDR path.
    key = plan.key(ctx.project.id, encoder)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="proxy",
                algorithm_version=f"{PROXY_VERSION}+ffmpeg-{caps.version}",
                input_keys=plan.fingerprints,
            ),
        )
    spec = builders.ProxySpec(
        inputs=[ctx.project.root / c.rel_path for c in plan.chapters],
        video_index=plan.video_index,
        audio_index=plan.audio_index,
        width=plan.width,
        height=plan.height,
        rate=plan.rate,
        hdr=hdr,
        full_range=plan.color_range == "pc",
        encoder=encoder,
        bitrate=plan.bitrate,
        video_starts=[c.start_pts * c.tb for c in plan.chapters],
        video_durations=[c.duration_ticks * plan.tb for c in plan.chapters],
        hwaccel="videotoolbox" if encoder == "h264_videotoolbox" else None,
        projection=plan.projection,
        lut=ctx.project.artifacts.path("lut", plan.lut_key) if plan.lut_key else None,
    )
    with ctx.project.artifacts.writer("proxy", key, ".mp4", provenance_id=prov) as tmp:
        spec.out = tmp
        try:
            run(binaries, builders.proxy(spec))
        except FFmpegError:
            if spec.hwaccel is None:
                raise
            spec.hwaccel = None  # hardware decode refused this source: decode in software
            run(binaries, builders.proxy(spec))
        written = probing.parse_probe(probing.ffprobe(binaries, tmp))
    frames = written.video_streams[0].nb_frames or round_fraction(
        plan.duration_ticks * plan.tb * plan.rate, Rounding.CEIL
    )
    frame_ticks = (
        None if cfr_verified(plan) else source_frame_ticks(binaries, ctx.project.root, plan)
    )
    tmap = build_tick_map(plan, frames, frame_ticks)
    ctx.project.artifacts.put_json("tickmap", f"{key}-map", tmap, provenance_id=prov)
    return {"proxy": key, "frames": frames, "tickmap": tmap["kind"]}


inventory.ASSET_STAGES.append(inventory.StageDef("proxy", "media.proxy", ResourceClass.GPU_ENCODE))


def _missing_errors() -> tuple[type[BaseException], ...]:
    from mosaic.jobs.registry import PermanentError
    from mosaic.storage.artifacts import ArtifactMissingError

    return (ArtifactMissingError, PermanentError, FileNotFoundError)


# Why a proxy cannot be served: not made yet, or its files are gone.
PROXY_MISSING = _missing_errors()
