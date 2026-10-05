"""L1 visual analysis per asset (ARCHITECTURE.md §8 stages 4–6): shots, samples, tech
metrics and optical-flow shake, from the proxy. Everything is written in logical source
ticks through the proxy tick map (invariant 4).

Pass A streams every proxy frame at 256 px wide: HSV content values (shots, freezes) and
phase-correlation shifts (motion, shake). Pass B extracts the candidate sample frames at
proxy size: frame metrics, pHash de-duplication and thumbnails.
"""

from __future__ import annotations

import io
from fractions import Fraction
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy import delete

from mosaic.core.keys import artifact_key
from mosaic.core.modes import ModeConfig, task_mode
from mosaic.core.time import Rounding, round_fraction
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import PermanentError, task
from mosaic.library.purge import purge_sample_derived
from mosaic.media import inventory, l1
from mosaic.media import proxy as _proxy  # noqa: F401 - registers "proxy" first
from mosaic.media.ffmpeg import builders
from mosaic.media.ffmpeg.run import stream_stdout
from mosaic.media.proxy import ProxyInfo, load_proxy, proxy_frame_to_source_ticks
from mosaic.media.tools import media_tools
from mosaic.storage import metrics, provenance, stage_state
from mosaic.storage.models_project import Asset, SampleFrame, Shot, TechMetric

VISUAL_VERSION = "visual/1"
ANALYSIS_WIDTH = 256
SAMPLE_INTERVAL = Fraction(3)  # Balanced (ANALYSIS_MODES.md §2)
SCENE_OFFSET = Fraction(1, 2)  # scene-change sample: 0.5 s into the shot
MIN_SHOT = Fraction(1, 2)
FORCED_MAX_SHOT = Fraction(60)
DUP_HAMMING = 6
THUMB_WIDTH = 640
BATCH = 48  # sample frames per FFmpeg select call (≤ builders.MAX_SELECT_FRAMES)
NOT_NORMALIZED = ("freeze",)  # flags, not measurements
VISUAL_METRICS = (
    "sharpness",
    "exposure_mean",
    "clip_low",
    "clip_high",
    "noise",
    "obstruction",
    "shake",
    "motion",
    "freeze",
)

CONFIG: dict[str, Any] = {
    "width": ANALYSIS_WIDTH,
    "interval": SAMPLE_INTERVAL,
    "scene_offset": SCENE_OFFSET,
    "min_shot": MIN_SHOT,
    "forced_max": FORCED_MAX_SHOT,
    "dup_hamming": DUP_HAMMING,
    "threshold": l1.ADAPTIVE_THRESHOLD,
    "min_content": l1.MIN_CONTENT_VAL,
}


def _even(x: Fraction) -> int:
    return max(2, 2 * round_fraction(x / 2, Rounding.NEAREST))


def config_for(mode: ModeConfig) -> dict[str, Any]:
    """The key config for a mode. Balanced is exactly ``CONFIG`` (existing analyses stay
    valid); other modes override the sampling interval, forced split and detector."""
    if (mode.sample_interval, mode.forced_max_shot, mode.detector) == (
        SAMPLE_INTERVAL,
        FORCED_MAX_SHOT,
        "adaptive",
    ):
        return CONFIG
    return CONFIG | {
        "interval": mode.sample_interval,
        "forced_max": mode.forced_max_shot,
        "detector": mode.detector,
        "threshold_cut": l1.THRESHOLD_CUT,
    }


def _key(ctx: TaskContext, px: ProxyInfo) -> str:
    return artifact_key(
        "visual",
        project_id=ctx.project.id,
        # The asset is part of the key: rows are per asset, and two identical files share
        # one proxy blob but are two assets.
        inputs={"proxy": px.key, "asset": ctx.params["asset_id"]},
        config=config_for(task_mode(ctx)),
        version=VISUAL_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    """The artifact exists and the asset's rows came from it (ADR 0020)."""
    px = load_proxy(ctx.project, ctx.params["asset_id"], task_mode(ctx))
    key = _key(ctx, px)
    if not ctx.project.artifacts.exists("visual", key):
        return False
    with ctx.project.db.session() as s:
        return stage_state.is_current(s, ctx.params["asset_id"], "visual", key)


def pass_a(ctx: TaskContext, px: ProxyInfo) -> tuple[list[float], list[tuple[float, float]]]:
    binaries, _ = media_tools()
    w = ANALYSIS_WIDTH
    h = _even(Fraction(w * px.height, px.width))
    content: list[float] = []
    shifts: list[tuple[float, float]] = []
    prev_hsv = prev_gray = None
    for i, buf in enumerate(stream_stdout(binaries, builders.raw_frames(px.path, w, h), w * h * 3)):
        if i % 500 == 0:
            ctx.check_cancelled()
        rgb = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
        hsv = l1.rgb_to_hsv(rgb)
        gray = l1.luma(rgb)
        if prev_hsv is None or prev_gray is None:
            content.append(0.0)
            shifts.append((0.0, 0.0))
        else:
            content.append(l1.content_value(prev_hsv, hsv))
            shifts.append(l1.phase_shift(prev_gray, gray))
        prev_hsv, prev_gray = hsv, gray
    return content, shifts


def plan_samples(
    shots: list[tuple[int, int, str]], rate: Fraction, every: Fraction = SAMPLE_INTERVAL
) -> list[tuple[int, int, str]]:
    """``(frame, shot_index, reason)``: one scene-change frame per shot plus fixed-interval
    frames (every ``every`` seconds) that are at least 1 s away from it."""
    interval = max(1, round_fraction(every * rate, Rounding.NEAREST))
    offset = round_fraction(SCENE_OFFSET * rate, Rounding.NEAREST)
    gap = round_fraction(rate, Rounding.NEAREST)
    out: list[tuple[int, int, str]] = []
    for si, (start, end, _) in enumerate(shots):
        scene = start + min(offset, max(0, (end - start) // 2))
        out.append((scene, si, "scene"))
        f = start + interval
        while f < end:
            if abs(f - scene) >= gap:
                out.append((f, si, "interval"))
            f += interval
    return sorted(out)


def _thumb(rgb: np.ndarray) -> bytes:
    img = Image.fromarray(rgb)
    if img.width > THUMB_WIDTH:
        img = img.resize(
            (THUMB_WIDTH, round(img.height * THUMB_WIDTH / img.width)), Image.Resampling.LANCZOS
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@task("media.visual", is_done=_is_done)
def visual_task(ctx: TaskContext) -> dict[str, Any]:
    binaries, _ = media_tools()
    asset_id = ctx.params["asset_id"]
    px = load_proxy(ctx.project, asset_id, task_mode(ctx))
    key = _key(ctx, px)
    tmap = px.tickmap
    with ctx.project.db.session() as s:
        asset = s.get(Asset, asset_id)
        assert asset is not None
        duration = asset.duration_ticks or 0

    def ticks(frame: int) -> int:
        return proxy_frame_to_source_ticks(tmap, frame)

    ctx.set_stage("shots")
    content, shifts = pass_a(ctx, px)
    n = len(content)
    mode = task_mode(ctx)
    min_len = max(1, round_fraction(MIN_SHOT * px.rate, Rounding.NEAREST))
    max_len = round_fraction(mode.forced_max_shot * px.rate, Rounding.NEAREST)
    detect = l1.threshold_cuts if mode.detector == "threshold" else l1.adaptive_cuts
    starts = [0, *detect(content, min_len)]
    shots = l1.force_split(starts, n, max_len, mode.detector)
    candidates = plan_samples(shots, px.rate, mode.sample_interval)

    with ctx.write() as s:
        stage_state.mark(s, asset_id, "visual", "")  # rows are being replaced
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="visual",
                algorithm_version=VISUAL_VERSION,
                input_keys=[px.key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
        s.execute(
            delete(TechMetric).where(
                TechMetric.asset_id == asset_id, TechMetric.name.in_(VISUAL_METRICS)
            )
        )
        purge_sample_derived(s, asset_id)  # segments and embeddings depend on these rows
        s.execute(delete(SampleFrame).where(SampleFrame.asset_id == asset_id))
        s.execute(delete(Shot).where(Shot.asset_id == asset_id))
        shot_rows: list[Shot] = []
        for i, (a, b, method) in enumerate(shots):
            row = Shot(
                asset_id=asset_id,
                index=i,
                start_ticks=ticks(a),
                end_ticks=ticks(b) if b < n else duration,
                method=method,
                provenance_id=prov,
            )
            s.add(row)
            shot_rows.append(row)
        s.flush()
        shot_ids = [r.id for r in shot_rows]

    # Pass B: candidate frames at proxy size. Compute first, write thumbnails, then insert
    # rows in one write session (artifacts must not be recorded inside a write session).
    ctx.set_stage("samples")
    size = px.width * px.height * 3
    last_kept: dict[int, tuple[int, dict[str, Any]]] = {}  # shot index → (phash, record)
    kept = 0
    for b0 in range(0, len(candidates), BATCH):
        ctx.check_cancelled()
        batch = candidates[b0 : b0 + BATCH]
        cmd = builders.select_frames(px.path, [f for f, _, _ in batch], px.rate)
        records: list[dict[str, Any]] = []
        # Frames are matched to samples by position, so the count must be exact; the stream
        # is consumed to EOF so FFmpeg's exit code is checked. Rows are written only after.
        decoded = 0
        for buf in stream_stdout(binaries, cmd, size):
            if decoded >= len(batch):
                raise PermanentError(f"asset {asset_id}: FFmpeg returned extra sample frames")
            frame, si, reason = batch[decoded]
            decoded += 1

            rgb = np.frombuffer(buf, dtype=np.uint8).reshape(px.height, px.width, 3)
            gray = l1.luma(rgb)
            ph = l1.phash(gray)
            rec: dict[str, Any] = {
                "frame": frame,
                "si": si,
                "reason": reason,
                "ph": ph,
                "dup": None,
                "metrics": None,
                "image_key": None,
            }
            if reason == "interval" and si in last_kept:
                prev_hash, prev = last_kept[si]
                if l1.hamming(ph, prev_hash) <= DUP_HAMMING:
                    rec["dup"] = prev
            if rec["dup"] is None:
                last_kept[si] = (ph, rec)
                rec["metrics"] = l1.frame_metrics(gray)
                rec["image_key"] = f"frame-{key[-24:]}-{frame}"
                ctx.project.artifacts.put_bytes(
                    "frame", rec["image_key"], _thumb(rgb), provenance_id=prov, ext=".jpg"
                )
            records.append(rec)
        if decoded != len(batch):
            raise PermanentError(
                f"asset {asset_id}: expected {len(batch)} sample frames, decoded {decoded}"
            )
        with ctx.write() as s:
            for rec in records:
                dup = rec["dup"]
                sample = SampleFrame(
                    asset_id=asset_id,
                    shot_id=shot_ids[rec["si"]],
                    ticks=ticks(rec["frame"]),
                    reason=rec["reason"],
                    phash=f"{rec['ph']:016x}",
                    kept=dup is None,
                    dup_of=dup["id"] if dup else None,
                    dup_reason="phash" if dup else None,
                    image_key=rec["image_key"],
                    provenance_id=prov,
                )
                s.add(sample)
                s.flush()
                rec["id"] = sample.id
                m = rec["metrics"]
                if m is None:
                    continue
                kept += 1
                for name in (
                    "sharpness",
                    "exposure_mean",
                    "clip_low",
                    "clip_high",
                    "noise",
                    "obstruction",
                ):
                    s.add(
                        TechMetric(
                            asset_id=asset_id,
                            sample_id=sample.id,
                            start_ticks=sample.ticks,
                            end_ticks=sample.ticks,
                            name=name,
                            value=getattr(m, name),
                            provenance_id=prov,
                        )
                    )

    # Motion and shake per second, freezes.
    ctx.set_stage("motion")
    sec = max(1, round_fraction(px.rate, Rounding.NEAREST))
    smooth = max(1, round_fraction(px.rate / 2, Rounding.NEAREST))
    jit = l1.jitter(shifts, ANALYSIS_WIDTH, smooth)
    speed = [float(np.hypot(dx, dy)) / ANALYSIS_WIDTH for dx, dy in shifts]
    with ctx.write() as s:
        for w_i, (shake, motion) in enumerate(
            zip(l1.per_window(jit, sec, "rms"), l1.per_window(speed, sec, "mean"), strict=True)
        ):
            a = w_i * sec
            b = min(n, a + sec)
            for name, value in (("shake", shake), ("motion", motion)):
                s.add(
                    TechMetric(
                        asset_id=asset_id,
                        start_ticks=ticks(a),
                        end_ticks=ticks(b) if b < n else duration,
                        name=name,
                        value=value,
                        provenance_id=prov,
                    )
                )
        for a, b in l1.freeze_runs(content, sec):
            s.add(
                TechMetric(
                    asset_id=asset_id,
                    start_ticks=ticks(a),
                    end_ticks=ticks(b) if b < n else duration,
                    name="freeze",
                    value=1.0,
                    provenance_id=prov,
                )
            )
    series = {
        "rate": f"{px.rate.numerator}/{px.rate.denominator}",
        "frames": n,
        "content": [round(c, 3) for c in content],
        "shift": [[round(dx, 2), round(dy, 2)] for dx, dy in shifts],
    }
    ctx.project.artifacts.put_json("motion", f"motion-{key[-32:]}", series, provenance_id=prov)
    ctx.project.artifacts.put_json(
        "visual",
        key,
        {"shots": len(shots), "samples": len(candidates), "kept": kept},
        provenance_id=prov,
    )
    with ctx.write() as s:
        stage_state.mark(s, asset_id, "visual", key)
    return {"shots": len(shots), "samples": len(candidates), "kept": kept}


@task("analysis.normalize")
def normalize_task(ctx: TaskContext) -> dict[str, Any]:
    """Project-normalized percentiles for every deterministic metric (§5.3)."""
    with ctx.write() as s:
        updated = metrics.normalize_percentiles(s, exclude=NOT_NORMALIZED)
    return {"rows": updated}


inventory.ASSET_STAGES.append(
    inventory.StageDef("visual", "media.visual", ResourceClass.CPU, after=("proxy",))
)
inventory.PROJECT_STAGES.append(
    inventory.StageDef("normalize", "analysis.normalize", ResourceClass.CPU)
)
