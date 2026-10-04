"""Proxies (ARCHITECTURE.md §8 stage 3): 720p H.264 8-bit SDR Rec.709 CFR, plus a tick map.

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
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import select

from mosaic.core.keys import artifact_key
from mosaic.core.time import Rounding, format_rational, parse_rational, round_fraction
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass, TaskSpec
from mosaic.jobs.registry import PermanentError, task
from mosaic.media import inventory
from mosaic.media import probe as probing
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import FFmpegError, run
from mosaic.media.tools import media_tools
from mosaic.storage import provenance
from mosaic.storage.models_project import Asset, AssetFile, MediaFile, MediaStream
from mosaic.storage.projects import Project

PROXY_VERSION = "proxy/1"
PROXY_SHORT_SIDE = 720
PROXY_MAX_RATE = Fraction(30)
PROXY_BITRATE = "3M"


def proxy_rate(source_rate: Fraction | None) -> Fraction:
    """Source rate, halved until ≤ 30 fps (59.94 → 29.97, 120 → 30); 30 when unknown."""
    rate = source_rate or PROXY_MAX_RATE
    while rate > PROXY_MAX_RATE + Fraction(1, 1000):
        rate /= 2
    return rate


def proxy_size(display_w: int, display_h: int) -> tuple[int, int]:
    """Short side 720 (never upscaled), even dimensions, display aspect preserved."""
    short = min(display_w, display_h)
    target = min(PROXY_SHORT_SIDE, short)
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

    @property
    def fingerprints(self) -> list[str]:
        return [c.fingerprint for c in self.chapters]

    def key(self, project_id: str, encoder: str) -> str:
        # The FFmpeg version is recorded in provenance but not in the key: a rebuilt
        # FFmpeg produces an equivalent proxy, so existing proxies stay valid.
        return artifact_key(
            "proxy",
            project_id=project_id,
            inputs={"files": self.fingerprints, "v": self.video_index, "a": self.audio_index},
            config={
                "w": self.width,
                "h": self.height,
                "rate": self.rate,
                "color": self.color_hint,
                "range": self.color_range,
                "encoder": encoder,
                "bitrate": PROXY_BITRATE,
            },
            version=PROXY_VERSION,
        )


def plan_for(project: Project, asset_id: int) -> ProxyPlan:
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
        chapters = []
        for r in rows:
            st = streams[r.AssetFile.media_file_id]
            chapters.append(
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
        first = streams[rows[0].AssetFile.media_file_id]
        w, h = proxy_size(
            asset.display_width or first.width or 1280,
            asset.display_height or first.height or 720,
        )
        source_rate = parse_rational(asset.rate) if asset.rate else None
        return ProxyPlan(
            asset_id=asset_id,
            chapters=chapters,
            video_index=asset.video_stream_index,
            audio_index=asset.audio_stream_index,
            color_hint=asset.color_hint,
            color_range=first.color_range,
            width=w,
            height=h,
            source_rate=source_rate,
            rate=proxy_rate(source_rate),
            tb=parse_rational(asset.tb),
            duration_ticks=asset.duration_ticks or 0,
            vfr=asset.vfr,
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
    _, caps = media_tools()
    encoders = caps.h264_encoders()
    if not encoders:
        raise PermanentError("no H.264 encoder available in this FFmpeg build")
    return encoders[0]


def proxy_key(project: Project, asset_id: int) -> str:
    """The proxy artifact key for an asset's current files and settings."""
    return plan_for(project, asset_id).key(project.id, _encoder())


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


def load_proxy(project: Project, asset_id: int) -> ProxyInfo:
    """The finished proxy of an asset (for downstream analysis stages)."""
    plan = plan_for(project, asset_id)
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
    key = proxy_key(ctx.project, ctx.params["asset_id"])
    store = ctx.project.artifacts
    return store.exists("proxy", key) and store.exists("tickmap", f"{key}-map")


@task("media.proxy", is_done=_is_done)
def proxy_task(ctx: TaskContext) -> dict[str, Any]:
    binaries, caps = media_tools()
    plan = plan_for(ctx.project, ctx.params["asset_id"])
    encoder = _encoder()
    hdr = plan.color_hint if plan.color_hint in ("hlg", "pq") else None
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
        bitrate=PROXY_BITRATE,
        video_starts=[c.start_pts * c.tb for c in plan.chapters],
        video_durations=[c.duration_ticks * plan.tb for c in plan.chapters],
        hwaccel="videotoolbox" if encoder == "h264_videotoolbox" else None,
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


def plan_proxy(asset: Asset) -> list[TaskSpec]:
    return [
        TaskSpec(
            kind="media.proxy",
            stage="proxy",
            resource_class=ResourceClass.GPU_ENCODE,
            params={"asset_id": asset.id},
            label=f"proxy ast_{asset.id:04d}",
        )
    ]


inventory.ASSET_STAGES.append(plan_proxy)
