"""Render jobs (ARCHITECTURE.md §10): one ``render.chunk`` task per event, then
``render.assemble``.

Chunks are cached artifacts keyed by the event, its sources and the render profile, so an
unchanged event is reused by later versions and a resumed job skips finished chunks.
Previews read the proxies (720p); final renders read the original files (1080p).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import select

from mosaic.core.clock import now_iso
from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.jobs.context import TaskContext
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.devices import asset_lut
from mosaic.media.ffmpeg import render as rb
from mosaic.media.ffmpeg.builders import (
    audio_sample_count,
    ebur128_measure,
    ffprobe_json,
    ffprobe_stream_counts,
)
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import FFmpegError, run
from mosaic.media.proxy import load_proxy
from mosaic.media.tools import media_tools
from mosaic.render.plan import (
    AUDIO_VERSION,
    RENDER_VERSION,
    STILL_VERSION,
    TRANSITION_VERSION,
    Profile,
    SourceFile,
    assembly_key,
    audio_key,
    audio_span,
    chunk_key,
    dips,
    dissolve_frames,
    dissolve_key,
    dissolve_sides,
    fades,
    framing,
    is_split,
    picture,
    pieces,
    samples_for,
    still_key,
    title_key,
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


def _picture(v: EditVersion, index: int) -> dict[str, Any]:
    """What event ``index``'s own chunk renders: the event less its dissolves (ADR 0078)."""
    return picture(v.timeline, index)


def _chunk_plan(
    ctx: TaskContext, r: Render, v: EditVersion, index: int
) -> tuple[str, list[SourceFile]]:
    return _video_key(ctx, r, v, _picture(v, index))


def _video_key(
    ctx: TaskContext, r: Render, v: EditVersion, e: dict[str, Any]
) -> tuple[str, list[SourceFile]]:
    """The chunk key and source files of a picture: an event, part of one, or one side
    of a dissolve."""
    prof = _profile(r)
    if e.get("kind") == "title":  # a title card (ADR 0079): drawn, no source
        return title_key(ctx.project.id, e, prof, v.rate), []
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
    e: dict[str, Any],
    files: list[SourceFile],
    asset: Asset,
    out: Path,
    full_range: bool,
) -> rb.ChunkSpec:
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
        fade_in=fades(e, v.rate)[0],
        fade_out=fades(e, v.rate)[1],
        dip_in=dips(e).get("dip_in", 0),
        dip_out=dips(e).get("dip_out", 0),
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
    if is_split(v.timeline) and not ctx.project.artifacts.exists(
        "chunk", _audio_plan(ctx, r, v, index)[0]
    ):
        return False
    return not dissolve_frames(_event(v, index)) or ctx.project.artifacts.exists(
        "chunk", _dissolve_plan(ctx, r, v, index)[0]
    )


@task("render.chunk", is_done=_chunk_done)
def chunk_task(ctx: TaskContext) -> dict[str, Any]:
    """The event's chunk; in a version with J- or L-cuts, its audio chunk; and the
    dissolve into the next event, if there is one (ADR 0078)."""
    binaries, caps = media_tools()
    r, v = _render(ctx)
    index = int(ctx.params["index"])
    key, files = _chunk_plan(ctx, r, v, index)
    out: dict[str, Any] = {"chunk": key}
    if not ctx.project.artifacts.exists("chunk", key):
        out = _event_chunk(ctx, r, v, index, key, files, binaries, caps)
    if is_split(v.timeline):
        out["audio"] = _audio_chunk(ctx, r, v, index, binaries)
    if dissolve_frames(_event(v, index)):
        out["dissolve"] = _dissolve_chunk(ctx, r, v, index, binaries, caps)
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
    if _event(v, index).get("kind") == "title":
        return _still_chunk(ctx, r, v, index, key, None, binaries)
    if _event(v, index).get("kind") == "still":
        return _still_chunk(ctx, r, v, index, key, files[0], binaries)
    prov = _provenance(ctx, key, "render.chunk", RENDER_VERSION)
    with ctx.project.artifacts.writer("chunk", key, ".mov", provenance_id=prov) as tmp:
        spec = _side(ctx, r, v, _picture(v, index), files, caps, tmp)
        result = run(binaries, rb.chunk(spec))
        # Never cache a wrong chunk: exact frames and samples, or the task fails.
        _check(binaries, tmp, spec.frames, spec.samples, f"chunk {index}")
    return {"chunk": key, "ms": result.duration_ms}


def _provenance(ctx: TaskContext, key: str, kind: str, version: str) -> int:
    with ctx.write() as s:
        return provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind=kind,
                algorithm_version=version,
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )


def _check(binaries: FFmpegBinaries, path: Path, frames: int, samples: int, what: str) -> None:
    got = stream_counts(binaries, path)
    if got != (frames, samples):
        raise PermanentError(
            f"{what}: rendered {got[0]} frames / {got[1]} samples, expected {frames} / {samples}"
        )


def _side(
    ctx: TaskContext,
    r: Render,
    v: EditVersion,
    e: dict[str, Any],
    files: list[SourceFile],
    caps: Any,
    out: Path,
) -> rb.ChunkSpec:
    """The chunk spec of a video picture ``e``, with its LUT or tone mapping."""
    with ctx.project.db.session() as s:
        asset = s.get(Asset, int(e["asset_id"][4:]))
        assert asset is not None
        s.expunge(asset)
    with ctx.project.db.session() as s:
        lut = asset_lut(s, asset) if r.profile["kind"] == "final" else None
    hdr_source = asset.color_hint in ("hlg", "pq") and r.profile["kind"] == "final"
    if hdr_source and not lut and not caps.can_tonemap:
        raise PermanentError("HDR source needs zscale + tonemap; this FFmpeg build lacks them")
    spec = _spec(r, v, e, files, asset, out, _full_range(ctx, asset))
    if lut:
        spec.lut = ctx.project.artifacts.path("lut", lut)
        spec.hdr = None  # the LUT replaces tone mapping (ADR 0028)
    return spec


def _dissolve_plan(
    ctx: TaskContext, r: Render, v: EditVersion, index: int
) -> tuple[str, list[tuple[dict[str, Any], list[SourceFile]]]]:
    side_a, side_b, frames = dissolve_sides(v.timeline, index)
    key_a, files_a = _video_key(ctx, r, v, side_a)
    key_b, files_b = _video_key(ctx, r, v, side_b)
    key = dissolve_key(ctx.project.id, key_a, key_b, frames, v.rate)
    return key, [(side_a, files_a), (side_b, files_b)]


def _dissolve_chunk(
    ctx: TaskContext,
    r: Render,
    v: EditVersion,
    index: int,
    binaries: FFmpegBinaries,
    caps: Any,
) -> str:
    """The dissolve from event ``index`` into the next (ADR 0078): its own chunk."""
    key, sides = _dissolve_plan(ctx, r, v, index)
    if ctx.project.artifacts.exists("chunk", key):
        return key
    prov = _provenance(ctx, key, "render.dissolve", f"{RENDER_VERSION}+{TRANSITION_VERSION}")
    with ctx.project.artifacts.writer("chunk", key, ".mov", provenance_id=prov) as tmp:
        a, b = (_side(ctx, r, v, e, files, caps, tmp) for e, files in sides)
        run(binaries, rb.dissolve_chunk(a, b, tmp))
        _check(binaries, tmp, a.frames, a.samples, f"dissolve {index}")
    return key


def _still_chunk(
    ctx: TaskContext,
    r: Render,
    v: EditVersion,
    index: int,
    key: str,
    photo: SourceFile | None,
    binaries: FFmpegBinaries,
) -> dict[str, Any]:
    """A still event (ADR 0075): its canvas made with Pillow from the photo, then panned
    and zoomed by FFmpeg to exactly its frames, with silence. A title card (``photo``
    None, ADR 0079) is the same, from its drawn card and without motion."""
    import tempfile

    from mosaic.media.photo import PhotoError
    from mosaic.media.stills import canvas, motion_exprs
    from mosaic.media.titles import card_image

    e = _picture(v, index)
    prof = _profile(r)
    rate = parse_rational(v.rate)
    frames = e["timeline_out"]["frames"] - e["timeline_in"]["frames"]
    dip = dips(e)
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
            image = (
                card_image(e["title"]["title"], e["title"]["subtitle"], prof.width, prof.height)
                if photo is None
                else canvas(photo.path, prof.width, prof.height)
            )
        except PhotoError as exc:
            raise PermanentError(f"{e['asset_id']}: {exc}") from None
        canvas_path = Path(tmpdir) / "canvas.png"
        image.save(canvas_path, compress_level=1)  # decoded again for every frame
        zoom, x, y = motion_exprs(e["motion"], frames) if photo is not None else ("1", "0", "0")
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
            dip_in=dip.get("dip_in", 0),
            dip_out=dip.get("dip_out", 0),
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
    if e.get("kind") in ("still", "title"):
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
            fade_in=fades(e, v.rate)[0],
            fade_out=fades(e, v.rate)[1],
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


def _music_mix(
    ctx: TaskContext,
    binaries: FFmpegBinaries,
    v: EditVersion,
    sound: Path,
    mix: Path,
    samples: int,
) -> None:
    """The edit's sound with its music track under it, as one exact-length file."""
    from mosaic.core.runtime import server_mode
    from mosaic.editing.music import DUCK_DB, DUCK_RAMP, MusicPathError, check_path, speech_windows
    from mosaic.editing.request import Music
    from mosaic.storage import media_roots

    music = Music.model_validate(v.request["music"])
    try:
        track = check_path(music.path)
        if server_mode():  # still inside a media root now (ADR 0035), not only when saved
            if ctx.control is None:
                raise PermanentError("music track: the media roots can't be checked")
            media_roots.confine(ctx.control, str(track))
    except (MusicPathError, media_roots.PathRefusedError) as exc:
        raise PermanentError(f"music track: {exc}") from None
    if not _has_audio(binaries, track):
        raise PermanentError(f"music track {track.name}: it has no audio we can read")
    rate = parse_rational(v.rate)
    ramp_frames = round_fraction(2 * DUCK_RAMP * rate, Rounding.CEIL)
    duck = [
        (Fraction(a) / rate, Fraction(b) / rate) for a, b in speech_windows(v.timeline, ramp_frames)
    ]
    spec = rb.MusicSpec(
        audio=sound,
        audio_concat=sound.suffix == ".txt",
        music=track,
        samples=samples,
        level_db=music.level_db,
        fade_in=Fraction(music.fade_in_ms, 1000),
        fade_out=Fraction(music.fade_out_ms, 1000),
        duck=duck,
        duck_db=DUCK_DB,
        ramp=DUCK_RAMP,
        out=mix,
    )
    run(binaries, rb.music_mix(spec))
    got = stream_counts(binaries, mix)[1]
    if got != samples:
        raise PermanentError(f"music mix: {got} samples, expected {samples}")


def _has_audio(binaries: FFmpegBinaries, path: Path) -> bool:
    """Whether ffprobe reads an audio stream in ``path`` (a file it can't read has none)."""
    try:
        streams = json.loads(run(binaries, ffprobe_json(path)).stdout).get("streams", [])
    except (FFmpegError, ValueError):
        return False
    return any(st.get("codec_type") == "audio" for st in streams)


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
    keys: list[str] = []  # the picture chunks in order, dissolves between their pictures
    for index in range(len(events)):
        keys.append(_chunk_plan(ctx, r, v, index)[0])
        if dissolve_frames(events[index]):  # the dissolve sits between the two pictures
            keys.append(_dissolve_plan(ctx, r, v, index)[0])
    audio_keys: list[str] = []
    if is_split(v.timeline):  # J- and L-cuts: the sound from the audio chunks (ADR 0077)
        audio_keys = [_audio_plan(ctx, r, v, index)[0] for index in range(len(events))]
    for key in (*keys, *audio_keys):
        if not ctx.project.artifacts.exists("chunk", key):
            raise PermanentError(f"chunk {key} is missing")
    prof = _profile(r)
    out = output_path(ctx.project.workspace, r)
    out.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(v.timeline["duration"]["frames"])
    akey = assembly_key(
        ctx.project.id, keys, audio_keys, _music_signature(v), prof, v.rate, total_frames
    )
    earlier = _same_render(ctx, r, akey)
    if earlier is not None:  # an identical render exists: its file, not a new one (ADR 0083)
        source, metrics = earlier
        tmp = out.with_name(out.stem + ".part" + out.suffix)
        tmp.unlink(missing_ok=True)
        try:
            os.link(source, tmp)
        except OSError:
            shutil.copy2(source, tmp)
        tmp.replace(out)
    else:
        metrics = _assemble(ctx, binaries, r, v, keys, audio_keys, out)
    metrics = metrics | {"assembly_key": akey}
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


def _music_signature(v: EditVersion) -> dict[str, Any] | None:
    """The music track as the assembly depends on it: its settings, the file's size and
    modification time (a replaced track makes a new render), and the speech windows and
    duck it follows (they come from the events' audio intents, not from the chunks)."""
    from mosaic.editing.music import DUCK_DB, DUCK_RAMP, speech_windows

    music = v.request.get("music")
    if not music:
        return None
    ramp_frames = round_fraction(2 * DUCK_RAMP * parse_rational(v.rate), Rounding.CEIL)
    sig = dict(music) | {
        "duck": [list(w) for w in speech_windows(v.timeline, ramp_frames)],
        "duck_db": DUCK_DB,
        "ramp": str(DUCK_RAMP),
    }
    try:
        st = Path(str(music["path"])).stat()
    except OSError:  # gone: the mix will fail with a plain message; nothing to reuse
        return sig
    return sig | {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _same_render(ctx: TaskContext, r: Render, akey: str) -> tuple[Path, dict[str, Any]] | None:
    """A finished render of this edit with the same assembly key, whose file is there."""
    with ctx.project.db.session() as s:
        rows = s.scalars(
            select(Render)
            .where(Render.edit_id == r.edit_id, Render.status == "done", Render.id != r.id)
            .order_by(Render.id.desc())
        )
        for row in rows:
            if (row.metrics or {}).get("assembly_key") != akey or not row.path:
                continue
            path = ctx.project.workspace / row.path
            if path.is_file() and path.stat().st_size > 0:
                return path, dict(row.metrics) | {"reused_from": row.id}
    return None


def _assemble(
    ctx: TaskContext,
    binaries: FFmpegBinaries,
    r: Render,
    v: EditVersion,
    keys: list[str],
    audio_keys: list[str],
    out: Path,
) -> dict[str, Any]:
    """Concatenate the chunks, mix the music, normalize loudness; the render's metrics."""
    prof = _profile(r)
    list_file = out.with_suffix(".concat.txt")
    list_file.write_text(rb.concat_list([ctx.project.artifacts.path("chunk", k) for k in keys]))
    audio_list = None
    if audio_keys:
        audio_list = out.with_suffix(".audio.txt")
        audio_list.write_text(
            rb.concat_list([ctx.project.artifacts.path("chunk", k) for k in audio_keys])
        )
    rate = parse_rational(v.rate)
    total_frames = int(v.timeline["duration"]["frames"])
    total_samples = samples_for(total_frames, rate)
    sound, concat = audio_list or list_file, True
    mix = out.with_suffix(".music.mov")
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    try:
        if v.request.get("music"):  # the music bed goes under the edit's sound (ADR 0080)
            _music_mix(ctx, binaries, v, sound, mix, total_samples)
            sound, concat = mix, False
        measured = parse_loudnorm(run(binaries, rb.loudnorm_measure(sound, concat)).stderr)
        run(
            binaries,
            rb.assemble(
                list_file,
                tmp,
                measured,
                prof.container,
                total_samples,
                rate,
                None if sound == list_file else sound,
                concat,
            ),
        )
    finally:
        mix.unlink(missing_ok=True)
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
    return {
        "frames": total_frames,
        "rate": v.rate,
        "samples": total_samples,
        "loudness_lufs": loud,
        "true_peak_dbtp": peak,
        "normalized": measured is not None,
    }
