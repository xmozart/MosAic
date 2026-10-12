"""Render jobs (ARCHITECTURE.md §10): one ``render.chunk`` task per event, then
``render.assemble``.

Chunks are cached artifacts keyed by the event, its sources and the render profile, so an
unchanged event is reused by later versions and a resumed job skips finished chunks.
Previews read the proxies (720p); final renders read the original files (1080p).
"""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.core.time import parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.devices import asset_lut
from mosaic.media.ffmpeg import render as rb
from mosaic.media.ffmpeg.builders import (
    audio_sample_count,
    ebur128_measure,
    ffprobe_stream_counts,
)
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run
from mosaic.media.proxy import load_proxy
from mosaic.media.tools import media_tools
from mosaic.render.plan import (
    AUDIO_VERSION,
    RENDER_VERSION,
    STILL_VERSION,
    Profile,
    SourceFile,
    audio_key,
    audio_span,
    chunk_key,
    framing,
    is_split,
    pieces,
    samples_for,
    still_key,
)
from mosaic.storage import provenance
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    EditVersion,
    MediaFile,
    MediaStream,
    Render,
)


def _render(ctx: TaskContext) -> tuple[Render, EditVersion]:
    with ctx.project.db.session() as s:
        r = s.get(Render, int(ctx.params["render_id"]))
        if r is None:
            raise PermanentError(f"render {ctx.params['render_id']} not found")
        v = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == r.edit_id, EditVersion.version == r.version
            )
        )
        if v is None:
            raise PermanentError(f"edit version {r.edit_id}/{r.version} not found")
        return r, v


def _profile(r: Render) -> Profile:
    p = r.profile
    return Profile(
        p["kind"],
        p["width"],
        p["height"],
        p["encoder"],
        p["bitrate"],
        p["lossless"],
        p.get("fill", "auto"),
    )


def _event(v: EditVersion, index: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = v.timeline["tracks"][0]["events"]
    return events[index]


def _sources(ctx: TaskContext, asset: Asset, kind: str) -> list[SourceFile]:
    if kind == "preview":
        proxy = load_proxy(ctx.project, asset.id)
        return [SourceFile(proxy.path, 0, asset.duration_ticks or 0, Fraction(0), proxy.key)]
    with ctx.project.db.session() as s:
        rows = list(
            s.execute(
                select(AssetFile, MediaFile)
                .join(MediaFile, MediaFile.id == AssetFile.media_file_id)
                .where(AssetFile.asset_id == asset.id)
                .order_by(AssetFile.order)
            )
        )
        out = []
        for af, mf in rows:
            st = s.scalar(
                select(MediaStream).where(
                    MediaStream.media_file_id == mf.id,
                    MediaStream.stream_index == asset.video_stream_index,
                )
            )
            if st is None:
                raise PermanentError(f"{mf.rel_path}: video stream missing")
            out.append(
                SourceFile(
                    ctx.project.root / mf.rel_path,
                    af.logical_start_ticks,
                    af.duration_ticks,
                    Fraction(st.start_pts) * parse_rational(st.time_base),
                    mf.fingerprint,
                )
            )
    return out


def _photo_file(ctx: TaskContext, asset_id: int) -> SourceFile:
    """A still's photo: its first file (the still of a Live Photo), read-only."""
    with ctx.project.db.session() as s:
        row = s.execute(
            select(MediaFile)
            .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
            .where(AssetFile.asset_id == asset_id)
            .order_by(AssetFile.order)
            .limit(1)
        ).first()
    if row is None:
        raise PermanentError(f"ast_{asset_id:04d}: no photo file")
    mf = row[0]
    return SourceFile(ctx.project.root / mf.rel_path, 0, 0, Fraction(0), mf.fingerprint)


def _chunk_plan(
    ctx: TaskContext, r: Render, v: EditVersion, index: int
) -> tuple[str, list[SourceFile]]:
    e = _event(v, index)
    prof = _profile(r)
    if e.get("kind") == "still":  # a photo (ADR 0075): its file, never a proxy
        photo = _photo_file(ctx, int(e["asset_id"][4:]))
        return still_key(ctx.project.id, e, photo.fingerprint, prof, v.rate), [photo]
    with ctx.project.db.session() as s:
        asset = s.get(Asset, int(e["asset_id"][4:]))
        if asset is None or asset.tb is None or asset.video_stream_index is None:
            raise PermanentError(f"{e['asset_id']}: not a playable video asset")
        s.expunge(asset)
    files = _sources(ctx, asset, prof.kind)
    inputs = [f.fingerprint for f in files]
    if prof.kind == "final":  # previews read proxies, which already carry the LUT
        with ctx.project.db.session() as s:
            lut = asset_lut(s, asset)
        if lut:
            inputs.append(f"lut:{lut}")
    key = chunk_key(ctx.project.id, e, inputs, prof, v.rate)
    return key, files


def _spec(
    r: Render,
    v: EditVersion,
    index: int,
    files: list[SourceFile],
    asset: Asset,
    out: Path,
    full_range: bool,
) -> rb.ChunkSpec:
    e = _event(v, index)
    prof = _profile(r)
    rate = parse_rational(v.rate)
    assert asset.tb is not None
    assert asset.video_stream_index is not None
    tb = parse_rational(asset.tb)
    if parse_rational(e["source_in"]["tb"]) != tb or parse_rational(e["source_out"]["tb"]) != tb:
        raise PermanentError(f"{e['event_id']}: source time base differs from its asset's")
    frames = e["timeline_out"]["frames"] - e["timeline_in"]["frames"]
    src_rate = _source_rate(asset, prof.kind)
    audio = e["audio"]
    # Proxies carry the asset's first audio stream as their audio stream 1.
    if prof.kind == "preview":
        video_index, audio_index = 0, (1 if asset.audio_stream_index is not None else None)
    else:
        video_index, audio_index = asset.video_stream_index, asset.audio_stream_index
    hdr = asset.color_hint if asset.color_hint in ("hlg", "pq") and prof.kind == "final" else None
    return rb.ChunkSpec(
        pieces=pieces(
            e["source_in"]["ticks"],
            e["source_out"]["ticks"],
            tb,
            files,
            Fraction(1) / src_rate if src_rate else Fraction(1, 30),
        ),
        video_index=video_index,
        audio_index=audio_index,
        audio_enabled=bool(audio["source_enabled"]),
        gain_db=int(audio["gain_db"]),
        fade_in=Fraction(int(audio["fade_in_frames"])) / rate,
        fade_out=Fraction(int(audio["fade_out_frames"])) / rate,
        width=prof.width,
        height=prof.height,
        framing=framing(
            asset.display_width, asset.display_height, prof.width, prof.height, prof.fill
        ),
        focus=_focus(e),
        rate=rate,
        frames=frames,
        samples=samples_for(frames, rate),
        hdr=hdr,
        full_range=prof.kind == "final" and full_range,
        encoder=prof.encoder,
        bitrate=prof.bitrate,
        out=out,
        source_rate=src_rate,
    )


def _focus(e: dict[str, Any]) -> tuple[int, int] | None:
    f = (e.get("transform") or {}).get("focus")
    return (int(f["x"]), int(f["y"])) if f else None


def _source_rate(asset: Asset, kind: str) -> Fraction | None:
    """The rate of the frames being read: the proxy's for previews, else the source's."""
    if kind == "preview":
        from mosaic.media.proxy import proxy_rate

        return proxy_rate(parse_rational(asset.rate)) if asset.rate else None
    return parse_rational(asset.rate) if asset.rate else None


def _full_range(ctx: TaskContext, asset: Asset) -> bool:
    """Full-range (``pc``) sources are scaled to TV range (same rule as the proxy)."""
    with ctx.project.db.session() as s:
        rng = s.scalar(
            select(MediaStream.color_range)
            .join(AssetFile, AssetFile.media_file_id == MediaStream.media_file_id)
            .where(
                AssetFile.asset_id == asset.id,
                MediaStream.stream_index == asset.video_stream_index,
            )
            .order_by(AssetFile.order)
            .limit(1)
        )
    return rng == "pc"


def _chunk_done(ctx: TaskContext) -> bool:
    r, v = _render(ctx)
    index = int(ctx.params["index"])
    key, _ = _chunk_plan(ctx, r, v, index)
    if not ctx.project.artifacts.exists("chunk", key):
        return False
    return not is_split(v.timeline) or ctx.project.artifacts.exists(
        "chunk", _audio_plan(ctx, r, v, index)[0]
    )


@task("render.chunk", is_done=_chunk_done)
def chunk_task(ctx: TaskContext) -> dict[str, Any]:
    """The event's chunk and, in a version with J- or L-cuts, its audio chunk."""
    binaries, caps = media_tools()
    r, v = _render(ctx)
    index = int(ctx.params["index"])
    key, files = _chunk_plan(ctx, r, v, index)
    out: dict[str, Any] = {"chunk": key}
    if not ctx.project.artifacts.exists("chunk", key):
        out = _event_chunk(ctx, r, v, index, key, files, binaries, caps)
    if is_split(v.timeline):
        out["audio"] = _audio_chunk(ctx, r, v, index, binaries)
    return out


def _event_chunk(
    ctx: TaskContext,
    r: Render,
    v: EditVersion,
    index: int,
    key: str,
    files: list[SourceFile],
    binaries: FFmpegBinaries,
    caps: Any,
) -> dict[str, Any]:
    if _event(v, index).get("kind") == "still":
        return _still_chunk(ctx, r, v, index, key, files[0], binaries)
    with ctx.project.db.session() as s:
        asset = s.get(Asset, int(_event(v, index)["asset_id"][4:]))
        assert asset is not None
        s.expunge(asset)
    with ctx.project.db.session() as s:
        lut = asset_lut(s, asset) if r.profile["kind"] == "final" else None
    hdr_source = asset.color_hint in ("hlg", "pq") and r.profile["kind"] == "final"
    if hdr_source and not lut and not caps.can_tonemap:
        raise PermanentError("HDR source needs zscale + tonemap; this FFmpeg build lacks them")
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="render.chunk",
                algorithm_version=RENDER_VERSION,
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
    with ctx.project.artifacts.writer("chunk", key, ".mov", provenance_id=prov) as tmp:
        spec = _spec(r, v, index, files, asset, tmp, _full_range(ctx, asset))
        if lut:
            spec.lut = ctx.project.artifacts.path("lut", lut)
            spec.hdr = None  # the LUT replaces tone mapping (ADR 0028)
        result = run(binaries, rb.chunk(spec))
        # Never cache a wrong chunk: exact frames and samples, or the task fails.
        frames, samples = stream_counts(binaries, tmp)
        if (frames, samples) != (spec.frames, spec.samples):
            raise PermanentError(
                f"chunk {index}: rendered {frames} frames / {samples} samples, "
                f"expected {spec.frames} / {spec.samples}"
            )
    return {"chunk": key, "ms": result.duration_ms}


def _still_chunk(
    ctx: TaskContext,
    r: Render,
    v: EditVersion,
    index: int,
    key: str,
    photo: SourceFile,
    binaries: FFmpegBinaries,
) -> dict[str, Any]:
    """A still event (ADR 0075): its canvas made with Pillow from the photo, then panned
    and zoomed by FFmpeg to exactly its frames, with silence."""
    import tempfile

    from mosaic.media.photo import PhotoError
    from mosaic.media.stills import canvas, motion_exprs

    e = _event(v, index)
    prof = _profile(r)
    rate = parse_rational(v.rate)
    frames = e["timeline_out"]["frames"] - e["timeline_in"]["frames"]
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="render.chunk",
                algorithm_version=f"{RENDER_VERSION}+{STILL_VERSION}",
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
    with (
        tempfile.TemporaryDirectory(prefix="mosaic-still-") as tmpdir,
        ctx.project.artifacts.writer("chunk", key, ".mov", provenance_id=prov) as tmp,
    ):
        try:
            image = canvas(photo.path, prof.width, prof.height)
        except PhotoError as exc:
            raise PermanentError(f"{e['asset_id']}: {exc}") from None
        canvas_path = Path(tmpdir) / "canvas.png"
        image.save(canvas_path, compress_level=1)  # decoded again for every frame
        zoom, x, y = motion_exprs(e["motion"], frames)
        spec = rb.StillSpec(
            canvas=canvas_path,
            zoom=zoom,
            x=x,
            y=y,
            width=prof.width,
            height=prof.height,
            rate=rate,
            frames=frames,
            samples=samples_for(frames, rate),
            encoder=prof.encoder,
            bitrate=prof.bitrate,
            out=tmp,
        )
        result = run(binaries, rb.still_chunk(spec))
        got = stream_counts(binaries, tmp)
        if got != (spec.frames, spec.samples):
            raise PermanentError(
                f"chunk {index}: rendered {got[0]} frames / {got[1]} samples, "
                f"expected {spec.frames} / {spec.samples}"
            )
    return {"chunk": key, "ms": result.duration_ms}


def _audio_plan(
    ctx: TaskContext, r: Render, v: EditVersion, index: int
) -> tuple[str, list[SourceFile], Asset | None]:
    """An audio chunk's key, files and asset (None for a still: silence)."""
    e = _event(v, index)
    prof = _profile(r)
    if e.get("kind") == "still":
        return audio_key(ctx.project.id, e, [], prof, v.rate), [], None
    with ctx.project.db.session() as s:
        asset = s.get(Asset, int(e["asset_id"][4:]))
        if asset is None or asset.tb is None:
            raise PermanentError(f"{e['asset_id']}: not a playable video asset")
        s.expunge(asset)
    files = _sources(ctx, asset, prof.kind)
    key = audio_key(ctx.project.id, e, [f.fingerprint for f in files], prof, v.rate)
    return key, files, asset


def _audio_chunk(
    ctx: TaskContext, r: Render, v: EditVersion, index: int, binaries: FFmpegBinaries
) -> str:
    """The event's heard window as an audio-only chunk (ADR 0077), exactly its samples."""
    key, files, asset = _audio_plan(ctx, r, v, index)
    if ctx.project.artifacts.exists("chunk", key):
        return key
    e = _event(v, index)
    prof = _profile(r)
    rate = parse_rational(v.rate)
    src_in, src_out, frames = audio_span(e)
    audio = e["audio"]
    index_in_file: int | None = None
    parts: list[rb.Piece] = []
    if asset is not None and asset.tb is not None and audio["source_enabled"]:
        index_in_file = (
            (1 if asset.audio_stream_index is not None else None)
            if prof.kind == "preview"
            else asset.audio_stream_index
        )
        parts = pieces(src_in["ticks"], src_out["ticks"], parse_rational(asset.tb), files)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="render.audio",
                algorithm_version=f"{RENDER_VERSION}+{AUDIO_VERSION}",
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
    with ctx.project.artifacts.writer("chunk", key, ".mov", provenance_id=prov) as tmp:
        spec = rb.AudioSpec(
            pieces=parts,
            audio_index=index_in_file if parts else None,
            gain_db=int(audio["gain_db"]),
            fade_in=Fraction(int(audio["fade_in_frames"])) / rate,
            fade_out=Fraction(int(audio["fade_out_frames"])) / rate,
            samples=samples_for(frames, rate),
            out=tmp,
        )
        run(binaries, rb.audio_chunk(spec))
        got = stream_counts(binaries, tmp)[1]
        if got != spec.samples:
            raise PermanentError(
                f"audio chunk {index}: rendered {got} samples, expected {spec.samples}"
            )
    return key


_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)
_EBUR128 = re.compile(r"I:\s+(-?[\d.]+|-inf) LUFS.*?Peak:\s+(-?[\d.]+|-inf) dBFS", re.S)


def parse_loudnorm(stderr: str) -> rb.Loudness | None:
    m = _LOUDNORM_JSON.findall(stderr)
    if not m:
        return None
    data = json.loads(m[-1])
    try:
        values = {
            k: float(data[k])
            for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        }
    except (KeyError, ValueError):
        return None
    if values["input_i"] < -70:  # silence: nothing to normalize
        return None
    return rb.Loudness(**values)


def parse_ebur128(stderr: str) -> tuple[float | None, float | None]:
    m = _EBUR128.findall(stderr)
    if not m:
        return None, None
    i, peak = m[-1]
    return (None if i == "-inf" else float(i)), (None if peak == "-inf" else float(peak))


def stream_counts(binaries: FFmpegBinaries, path: Path) -> tuple[int, int]:
    """(video frames, audio samples) of a rendered file."""
    data = json.loads(run(binaries, ffprobe_stream_counts(path)).stdout)
    frames = samples = 0
    for st in data.get("streams", []):
        if st.get("codec_type") == "video":
            frames = int(st.get("nb_read_packets") or 0)
        elif st.get("codec_type") == "audio":
            tb = parse_rational(st.get("time_base", "1/48000"))
            samples = round(Fraction(int(st.get("duration_ts") or 0)) * tb * rb.AUDIO_RATE)
    return frames, samples


_SAMPLES = re.compile(r"Number of samples:\s*(\d+)")


def decoded_samples(binaries: FFmpegBinaries, path: Path) -> int:
    """Audio samples as a player decodes them. AAC's container duration also counts
    encoder priming/padding, so it cannot verify an MP4."""
    found = _SAMPLES.findall(run(binaries, audio_sample_count(path)).stderr)
    if not found:
        raise PermanentError(f"{path.name}: FFmpeg reported no audio sample count")
    return int(found[-1])


def output_path(workspace: Path, r: Render) -> Path:
    """One file per render (two renders of a version never share a file)."""
    ext = "mov" if r.profile.get("lossless") else "mp4"
    name = f"v{r.version:03d}-{r.profile['kind']}-r{r.id:04d}.{ext}"
    return workspace / "renders" / f"edt_{r.edit_id:04d}" / name


@task("render.assemble", checkpoint=True)
def assemble_task(ctx: TaskContext) -> dict[str, Any]:
    binaries, _ = media_tools()
    r, v = _render(ctx)
    if r.status == "cancelled":  # cancelled from S20 while its chunks ran
        return {"render_id": r.id, "cancelled": True}
    events = v.timeline["tracks"][0]["events"]
    paths = []
    for index in range(len(events)):
        key, _ = _chunk_plan(ctx, r, v, index)
        if not ctx.project.artifacts.exists("chunk", key):
            raise PermanentError(f"chunk {index} is missing")
        paths.append(ctx.project.artifacts.path("chunk", key))
    prof = _profile(r)
    out = output_path(ctx.project.workspace, r)
    out.parent.mkdir(parents=True, exist_ok=True)
    list_file = out.with_suffix(".concat.txt")
    list_file.write_text(rb.concat_list(paths))
    audio_list = None
    if is_split(v.timeline):  # J- and L-cuts: the sound from the audio chunks (ADR 0077)
        audio_paths = []
        for index in range(len(events)):
            key = _audio_plan(ctx, r, v, index)[0]
            if not ctx.project.artifacts.exists("chunk", key):
                raise PermanentError(f"audio chunk {index} is missing")
            audio_paths.append(ctx.project.artifacts.path("chunk", key))
        audio_list = out.with_suffix(".audio.txt")
        audio_list.write_text(rb.concat_list(audio_paths))
    rate = parse_rational(v.rate)
    total_frames = int(v.timeline["duration"]["frames"])
    total_samples = samples_for(total_frames, rate)
    measured = parse_loudnorm(run(binaries, rb.loudnorm_measure(audio_list or list_file)).stderr)
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    run(
        binaries,
        rb.assemble(list_file, tmp, measured, prof.container, total_samples, rate, audio_list),
    )
    frames, samples = stream_counts(binaries, tmp)
    if prof.container == "mp4":
        samples = decoded_samples(binaries, tmp)
    # PCM is exact; decoded AAC may differ by up to one 1024-sample frame at the end.
    slack = 0 if prof.container == "mov" else 1024
    if frames != total_frames or abs(samples - total_samples) > slack:
        raise PermanentError(
            f"assembled {frames} frames / {samples} samples, "
            f"expected {total_frames} / {total_samples}"
        )
    tmp.replace(out)
    list_file.unlink(missing_ok=True)
    if audio_list is not None:
        audio_list.unlink(missing_ok=True)
    loud, peak = parse_ebur128(run(binaries, ebur128_measure(out)).stderr)
    metrics = {
        "frames": total_frames,
        "rate": v.rate,
        "samples": total_samples,
        "loudness_lufs": loud,
        "true_peak_dbtp": peak,
        "normalized": measured is not None,
    }
    with ctx.write() as s:
        row = s.get(Render, r.id)
        assert row is not None
        if row.status == "cancelled":  # cancelled while assembling: no file is kept
            out.unlink(missing_ok=True)
            return {"render_id": r.id, "cancelled": True}
        row.status = "done"
        row.path = str(out.relative_to(ctx.project.workspace))
        row.metrics = metrics
        row.finished_at = now_iso()
    return {"render_id": r.id, "path": str(out), **metrics}
