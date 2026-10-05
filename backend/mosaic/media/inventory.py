"""L0 inventory tasks: scan → probe (per file) → group (ARCHITECTURE.md §8 stages 1–2).

Each handler is idempotent. Unsupported files are recorded with a human-readable reason
and a suggested fix; no single file can fail the job (invariant 14). Grouping works one
directory at a time so memory stays bounded on large projects (invariant 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.keys import artifact_key, digest
from mosaic.core.modes import PRESETS, ModeConfig, task_mode
from mosaic.core.time import Rounding, format_rational, round_fraction
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass, TaskSpec
from mosaic.jobs.registry import task
from mosaic.media import probe as probing
from mosaic.media.profiles import (
    PROFILES,
    AssetGroup,
    FileRecord,
    SidecarLink,
    is_hfr,
    low_bitrate,
    lrf_matches,
    profile_by_id,
    profile_for,
    select_audio,
)
from mosaic.media.scan import MediaType, fingerprint, is_offline, scan
from mosaic.media.tools import media_tools
from mosaic.storage import provenance
from mosaic.storage.models_project import Asset, AssetFile, MediaFile, MediaStream, Sidecar

PROBE_VERSION = "probe/1"
GROUP_VERSION = "group/1"
PROXY_SIDECARS = (".lrf", ".lrv")
_REPAIR = "Check that the copy finished; copy the file again from the camera or card."


@dataclass(frozen=True)
class StageDef:
    """A pipeline stage. Per-asset stages run once per video asset, after the stages named
    in ``after``; project stages run once, after every per-asset task and the project
    stages before them (``after`` is checked against the registration order). A stage's
    module imports the modules of the stages it runs after, so registration order never
    depends on which module happens to be imported first."""

    name: str
    kind: str
    resource_class: ResourceClass
    after: tuple[str, ...] = ()
    level: int = 1  # ANALYSIS_MODES §1: L2 and L3 stages run only in modes that include them


ASSET_STAGES: list[StageDef] = []
PROJECT_STAGES: list[StageDef] = []


def _included(st: StageDef, mode: ModeConfig) -> bool:
    return st.level <= 1 or (st.level == 2 and mode.l2) or (st.level == 3 and mode.l3)


def plan_stages(asset_ids: list[int], mode: ModeConfig | None = None) -> list[TaskSpec]:
    """Task specs for the registered stages the mode includes (Balanced when none is
    given); ``deps`` index into the returned list."""
    for stages in (ASSET_STAGES, PROJECT_STAGES):
        names = [st.name for st in stages]
        for st in stages:
            unknown = [a for a in st.after if a not in names[: names.index(st.name)]]
            if unknown:
                raise RuntimeError(f"stage {st.name!r} runs after unregistered or later {unknown}")
    mode = mode or PRESETS["balanced"]
    asset_stages = [st for st in ASSET_STAGES if _included(st, mode)]
    project_stages = [st for st in PROJECT_STAGES if _included(st, mode)]
    for st in asset_stages:
        dropped = [a for a in st.after if a not in {x.name for x in asset_stages}]
        if dropped:
            raise RuntimeError(f"stage {st.name!r} runs after {dropped}, which this mode skips")
    specs: list[TaskSpec] = []
    for aid in asset_ids:
        local: dict[str, int] = {}
        for st in asset_stages:
            specs.append(
                TaskSpec(
                    kind=st.kind,
                    stage=st.name,
                    resource_class=st.resource_class,
                    params={"asset_id": aid},
                    label=f"{st.name} ast_{aid:04d}",
                    deps=[local[a] for a in st.after],
                )
            )
            local[st.name] = len(specs) - 1
    per_asset = list(range(len(specs)))
    previous: list[int] = per_asset
    for st in project_stages:
        specs.append(
            TaskSpec(
                kind=st.kind,
                stage=st.name,
                resource_class=st.resource_class,
                label=st.name,
                deps=list(previous),
            )
        )
        previous = [len(specs) - 1]
    return specs


# ------------------------------------------------------------------------- scan


@task("analysis.scan")
def scan_task(ctx: TaskContext) -> dict[str, Any]:
    """Record every file under the root and spawn one probe task per probe-able file."""
    root = ctx.project.root
    now = now_iso()
    probe_specs: list[TaskSpec] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    offline_bytes = 0
    with ctx.write() as s:
        existing = {m.rel_path: m for m in s.scalars(select(MediaFile))}
        for f in scan(root):
            ctx.check_cancelled()
            seen.add(f.rel_path)
            counts[f.media_type.value] = counts.get(f.media_type.value, 0) + 1
            row = existing.get(f.rel_path)
            changed = row is None or (row.size, row.mtime_ns) != (f.size, f.mtime_ns)
            if row is None:
                row = MediaFile(rel_path=f.rel_path, created_at=now)
                s.add(row)
            if changed or row.status in ("offline", "missing"):
                row.size, row.mtime_ns, row.media_type = f.size, f.mtime_ns, f.media_type.value
                row.fingerprint, row.status, row.probe_key = "", "pending", None
                row.reason = row.suggested_fix = None
            if f.offline:
                row.status, row.reason = "offline", "File is in the cloud and not downloaded."
                offline_bytes += f.size
                continue
            if f.media_type is MediaType.PHOTO:
                row.status, row.reason = "deferred", "Photos are analyzed from M1."
                continue
            if f.media_type is MediaType.OTHER:
                row.status, row.reason = "unsupported", "Not a video, photo or audio file."
                continue
            if f.media_type is MediaType.SIDECAR and Path(f.rel_path).suffix.lower() not in (
                PROXY_SIDECARS
            ):
                row.status = "ok"
                continue
            s.flush()
            probe_specs.append(
                TaskSpec(
                    kind="media.probe",
                    stage="probe",
                    resource_class=ResourceClass.IO,
                    params={"media_file_id": row.id},
                    label=f.rel_path,
                )
            )
        for rel, row in existing.items():
            if rel not in seen:
                row.status, row.reason = "missing", "File is no longer in the folder."
    ids = ctx.spawn(probe_specs)
    ctx.spawn(
        [
            TaskSpec(
                kind="media.group",
                stage="group",
                resource_class=ResourceClass.CPU,
                deps=[("id", i) for i in ids],
                label="grouping",
            )
        ]
    )
    ctx.set_stage("probe")
    return {"files": counts, "probes": len(probe_specs), "offline_bytes": offline_bytes}


# ------------------------------------------------------------------------ probe


def _probe_key(ctx: TaskContext, fp: str, rel_path: str) -> str:
    _, caps = media_tools()
    return artifact_key(
        "probe",
        project_id=ctx.project.id,
        inputs={"fingerprint": fp, "path": rel_path},
        version=f"{PROBE_VERSION}+ffprobe-{caps.version}",
    )


def _probe_done(ctx: TaskContext) -> bool:
    with ctx.project.db.session() as s:
        row = s.get(MediaFile, ctx.params["media_file_id"])
        if row is None or row.status in ("pending", "offline", "missing"):
            return False
        if row.status == "unsupported":
            return True  # recorded with its reason; a changed file resets to pending
        return (
            row.probe_key is not None
            and row.probe_key == _probe_key(ctx, row.fingerprint, row.rel_path)
            and ctx.project.artifacts.exists("probe", row.probe_key)
        )


def _stream_row(mf_id: int, st: probing.StreamInfo, vfr: bool) -> MediaStream:
    return MediaStream(
        media_file_id=mf_id,
        stream_index=st.index,
        codec_type=st.codec_type,
        codec_name=st.codec_name,
        codec_tag=st.codec_tag,
        profile=st.profile,
        time_base=format_rational(st.time_base),
        start_pts=st.start_pts,
        duration_ts=st.duration_ts,
        nb_frames=st.nb_frames,
        width=st.width,
        height=st.height,
        rate=format_rational(st.rate) if st.rate else None,
        avg_rate=format_rational(st.avg_rate) if st.avg_rate else None,
        vfr=vfr,
        rotation=st.rotation,
        pix_fmt=st.pix_fmt,
        bit_depth=st.bit_depth,
        color_range=st.color_range,
        color_transfer=st.color_transfer,
        color_primaries=st.color_primaries,
        color_space=st.color_space,
        dovi=st.dovi,
        channels=st.channels,
        channel_layout=st.channel_layout,
        sample_rate=st.sample_rate,
        handler=st.handler,
    )


def _mark(
    ctx: TaskContext,
    status: str,
    reason: str | None,
    fix: str | None,
    *,
    fp: str = "",
    probe_key: str | None = None,
) -> None:
    with ctx.write() as s:
        r = s.get(MediaFile, ctx.params["media_file_id"])
        assert r is not None
        s.execute(delete(MediaStream).where(MediaStream.media_file_id == r.id))
        r.fingerprint, r.status, r.reason = fp, status, reason
        r.suggested_fix, r.probe_key = fix, probe_key


@task("media.probe", is_done=_probe_done)
def probe_task(ctx: TaskContext) -> dict[str, Any]:
    binaries, caps = media_tools()
    with ctx.project.db.session() as s:
        row = s.get(MediaFile, ctx.params["media_file_id"])
        assert row is not None
        rel_path, size = row.rel_path, row.size
    path = ctx.project.root / rel_path
    try:
        if is_offline(path.lstat()):  # evicted to the cloud since the scan: never download
            _mark(ctx, "offline", "File is in the cloud and not downloaded.", None)
            return {"status": "offline"}
        fp = fingerprint(path, size)
    except FileNotFoundError:
        _mark(ctx, "missing", "File is no longer in the folder.", None)
        return {"status": "missing"}
    except OSError as exc:
        _mark(
            ctx,
            "unsupported",
            f"Cannot read the file: {exc.strerror or exc}.",
            "Check the file's permissions, or copy it again.",
        )
        return {"status": "unsupported"}
    key = _probe_key(ctx, fp, rel_path)

    try:
        data = probing.ffprobe(binaries, path)
        result = probing.parse_probe(data)
    except probing.ProbeError as exc:
        known = profile_by_id("generic").capability(None, rel_path)
        _mark(
            ctx,
            "unsupported",
            known.reason or f"Could not read the file: {exc}.",
            known.fix or _REPAIR,
            fp=fp,
        )
        return {"status": "unsupported"}
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="probe",
                algorithm_version=f"{PROBE_VERSION}+ffprobe-{caps.version}",
                input_keys=[fp],
            ),
        )
    ctx.project.artifacts.put_json("probe", key, data, provenance_id=prov)

    rec = FileRecord(id=0, rel_path=rel_path, media_type=MediaType.VIDEO, probe=result, usable=True)
    profile = profile_for(rec)
    capability = profile.capability(result, rel_path)
    if capability.level == "unsupported":
        _mark(ctx, "unsupported", capability.reason, capability.fix, fp=fp, probe_key=key)
        return {"status": "unsupported"}
    video = result.video_streams
    if video:
        err = probing.decode_check(binaries, path, f"{video[0].index}")
        if err:
            codec = video[0].codec_name or "video"
            _mark(
                ctx,
                "unsupported",
                f"The {codec} stream cannot be decoded: {err}.",
                _REPAIR,
                fp=fp,
                probe_key=key,
            )
            return {"status": "unsupported"}

    vfr_streams = {
        st.index
        for st in video
        if st.maybe_vfr and probing.video_vfr_from_packets(binaries, path, st.index)
    }
    make, model = profile.camera(result)
    with ctx.write() as s:
        r = s.get(MediaFile, ctx.params["media_file_id"])
        assert r is not None
        s.execute(delete(MediaStream).where(MediaStream.media_file_id == r.id))
        for st in result.streams:
            s.add(_stream_row(r.id, st, st.index in vfr_streams))
        r.fingerprint, r.probe_key = fp, key
        audio_only = r.media_type == MediaType.AUDIO.value
        r.status = "deferred" if audio_only else "ok"
        r.reason = "Standalone audio files are used in a later version." if audio_only else None
        r.suggested_fix = None
        r.container = result.format_name.split(",")[0]
        r.bit_rate = result.bit_rate
        r.profile = profile.id
        r.capture_time = profile.capture_time(result)
        r.camera_make, r.camera_model = make, model
        status = r.status
    return {"status": status, "profile": profile.id}


# ------------------------------------------------------------------------ group


def _video_duration_ticks(rec: FileRecord, tb: Fraction) -> int:
    assert rec.probe is not None
    v = rec.probe.video_streams[0]
    if v.duration_ts is not None:
        seconds = v.duration_ts * v.time_base
    elif rec.probe.duration is not None:
        seconds = rec.probe.duration
    else:
        seconds = Fraction(0)
    return round_fraction(seconds / tb, Rounding.NEAREST)


def link_sidecars(sidecars: list[FileRecord], owners: list[FileRecord]) -> list[SidecarLink]:
    """Each sidecar independently: the first profile that finds its owner wins."""
    out: list[SidecarLink] = []
    for sc in sidecars:
        chosen: SidecarLink | None = None
        for profile in PROFILES:
            link = profile.sidecars([sc], owners)[0]
            if link.owner is not None:
                chosen = link
                break
            chosen = chosen or link
        assert chosen is not None
        out.append(chosen)
    return out


class _Grouper:
    def __init__(self, ctx: TaskContext, prov: int, vfr_files: set[int]) -> None:
        self.ctx = ctx
        self.prov = prov
        self.vfr_files = vfr_files
        self.produced: set[str] = set()
        self.summary: dict[str, int] = {}
        self.video_assets: list[int] = []
        self.now = now_iso()

    def _count(self, key: str) -> None:
        self.summary[key] = self.summary.get(key, 0) + 1

    def _asset(self, s: Session, key: str) -> Asset:
        self.produced.add(key)
        asset = s.scalar(select(Asset).where(Asset.group_key == key))
        if asset is None:
            asset = Asset(group_key=key, created_at=self.now, provenance_id=self.prov)
            s.add(asset)
        asset.provenance_id = self.prov
        return asset

    def _apply(self, s: Session, g: AssetGroup) -> Asset:
        asset = self._asset(s, g.key)
        profile = profile_by_id(g.profile)
        first = g.files[0] if g.kind != "live_photo" else g.files[-1]
        probe = first.probe
        v = probe.video_streams[0] if probe and probe.video_streams else None
        a = select_audio(probe) if probe else None
        asset.kind, asset.status, asset.reason = g.kind, g.status, g.reason
        asset.suggested_fix = None
        asset.profile = g.profile
        asset.color_hint = profile.color_hint(probe) if probe else "sdr"
        asset.video_stream_index = v.index if v else None
        asset.audio_stream_index = a.index if a else None
        asset.rotation = v.rotation if v else 0
        if v is not None and v.width and v.height:
            swap = v.rotation in (90, 270)
            asset.display_width = v.height if swap else v.width
            asset.display_height = v.width if swap else v.height
        asset.rate = format_rational(v.rate) if v and v.rate else None
        flags = set(g.flags)
        if is_hfr(v):
            flags.add("hfr")
        if probe and low_bitrate(probe, v):
            flags.add("low_bitrate_source")
        asset.hfr = "hfr" in flags
        asset.flags = sorted(flags)
        s.flush()
        s.execute(delete(AssetFile).where(AssetFile.asset_id == asset.id))
        if g.kind == "video" and probe is not None and v is not None:
            tb = v.time_base
            asset.tb = format_rational(tb)
            start = 0
            for order, rec in enumerate(g.files):
                dur = _video_duration_ticks(rec, tb)
                s.add(
                    AssetFile(
                        asset_id=asset.id,
                        order=order,
                        media_file_id=rec.id,
                        logical_start_ticks=start,
                        duration_ticks=dur,
                    )
                )
                start += dur
            asset.duration_ticks = start
            asset.vfr = any(r.id in self.vfr_files for r in g.files)
            asset.capture_time = profile.capture_time(probe)
            asset.camera_make, asset.camera_model = profile.camera(probe)
        for rec in g.files:
            s.execute(update(MediaFile).where(MediaFile.id == rec.id).values(asset_id=asset.id))
        self._count(f"{g.kind}:{g.status}")
        if asset.kind == "video" and asset.status == "ok":
            self.video_assets.append(asset.id)
        return asset

    def directory(self, rows: list[MediaFile]) -> None:
        store = self.ctx.project.artifacts
        records: list[FileRecord] = []
        profiles: dict[int, str | None] = {}
        unsupported: list[MediaFile] = []
        for mf in rows:
            probe = None
            if (
                mf.probe_key
                and mf.status in ("ok", "deferred")
                and store.exists("probe", mf.probe_key)
            ):
                probe = probing.parse_probe(store.get_json("probe", mf.probe_key))
            rec = FileRecord(
                mf.id, mf.rel_path, MediaType(mf.media_type), probe, usable=mf.status == "ok"
            )
            profiles[mf.id] = mf.profile
            if mf.status == "unsupported" and rec.media_type is not MediaType.SIDECAR:
                unsupported.append(mf)
            elif mf.status in ("ok", "deferred"):
                records.append(rec)
        media = [r for r in records if r.media_type is not MediaType.SIDECAR]
        sidecars = [r for r in records if r.media_type is MediaType.SIDECAR]
        by_profile: dict[str, list[FileRecord]] = {}
        for rec in media:
            pid = profiles[rec.id] or profile_for(rec).id
            by_profile.setdefault(pid, []).append(rec)
        owners = [r for r in media if r.media_type is MediaType.VIDEO and r.usable]
        links = link_sidecars(sidecars, owners)

        with self.ctx.write() as s:
            for pid, recs in sorted(by_profile.items()):
                for g in profile_by_id(pid).group(recs):
                    self._apply(s, g)
            for mf in unsupported:
                asset = self._asset(s, f"unsupported:{mf.rel_path}")
                asset.kind, asset.status, asset.profile = "unsupported", "unsupported", "generic"
                asset.reason, asset.suggested_fix = mf.reason, mf.suggested_fix
                asset.duration_ticks = None
                asset.tb = None
                s.flush()
                s.execute(update(MediaFile).where(MediaFile.id == mf.id).values(asset_id=asset.id))
                self._count("unsupported")
            ids = [r.id for r in sidecars]
            if ids:
                s.execute(delete(Sidecar).where(Sidecar.media_file_id.in_(ids)))
            for link in links:
                self._sidecar(s, link)

    def _sidecar(self, s: Session, link: SidecarLink) -> None:
        if link.owner is None:
            status, reason = "orphan", "No matching original file."
        elif not link.proxy_candidate:
            status, reason = "ignored", None
        elif link.sidecar.probe is None or link.owner.probe is None:
            status, reason = "invalid", "Camera proxy could not be read."
        else:
            reason = lrf_matches(link.owner.probe, link.sidecar.probe)
            status = "invalid" if reason else "valid"
        s.add(
            Sidecar(
                media_file_id=link.sidecar.id,
                owner_media_file_id=link.owner.id if link.owner else None,
                kind=link.kind,
                status=status,
                reason=reason,
                proxy_candidate=link.proxy_candidate and status == "valid",
                provenance_id=self.prov,
            )
        )

    def reconcile(self) -> None:
        """Assets not produced by this run lost their files: mark them missing."""
        with self.ctx.write() as s:
            # Membership is checked in Python: one bound variable per key would exceed
            # SQLite's limit on very large projects.
            stale_ids = [
                aid
                for aid, key in s.execute(select(Asset.id, Asset.group_key))
                if key not in self.produced
            ]
            for aid in stale_ids:
                asset = s.get(Asset, aid)
                assert asset is not None
                if asset.status != "missing":
                    self._count("missing")
                asset.status = "missing"
                asset.reason = "Its files are gone or changed; it is no longer in the library."
                s.execute(
                    update(MediaFile).where(MediaFile.asset_id == asset.id).values(asset_id=None)
                )
                s.execute(delete(AssetFile).where(AssetFile.asset_id == asset.id))
            gone = (
                select(Sidecar.id)
                .join(MediaFile, MediaFile.id == Sidecar.media_file_id)
                .where(MediaFile.status.in_(["missing", "offline"]))
            )
            s.execute(delete(Sidecar).where(Sidecar.id.in_(gone)))


@task("media.group")
def group_task(ctx: TaskContext) -> dict[str, Any]:
    """Group probed files into assets (chapters, pairs) and associate sidecars, one
    directory at a time."""
    with ctx.project.db.session() as s:
        listing = list(
            s.execute(
                select(MediaFile.id, MediaFile.rel_path, MediaFile.probe_key).order_by(
                    MediaFile.rel_path
                )
            )
        )
        vfr_files = set(
            s.scalars(
                select(MediaStream.media_file_id).where(
                    MediaStream.codec_type == "video", MediaStream.vfr.is_(True)
                )
            )
        )
    by_dir: dict[str, list[int]] = {}
    for mf_id, rel, _ in listing:
        by_dir.setdefault(str(PurePosixPath(rel).parent), []).append(mf_id)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="group",
                algorithm_version=GROUP_VERSION,
                # A digest, not the list: a project can hold tens of thousands of files.
                input_keys=[f"probe-set:{digest(sorted(k for _, _, k in listing if k))}"],
            ),
        )
    grouper = _Grouper(ctx, prov, vfr_files)
    for _, ids in sorted(by_dir.items()):
        ctx.check_cancelled()
        with ctx.project.db.session() as s:
            rows = list(
                s.scalars(
                    select(MediaFile).where(MediaFile.id.in_(ids)).order_by(MediaFile.rel_path)
                )
            )
        grouper.directory(rows)
    grouper.reconcile()
    planned = plan_stages(grouper.video_assets, task_mode(ctx))
    if planned:
        ctx.spawn(planned)
    ctx.set_stage("analysis")
    ctx.store.set_job_result(ctx.task.job_id, {"inventory": grouper.summary})
    return {"assets": grouper.summary, "spawned": len(planned)}
