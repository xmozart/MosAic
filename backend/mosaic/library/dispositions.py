"""Dispositions (ARCHITECTURE.md §8 stage 13): USE / MAYBE / REJECT with reasons.

Deterministic rules on the technical metrics (accidental recordings, black or obstructed
frames, freezes, extreme shake or blur) are combined with the vision observation's issues;
the most severe status wins and every contributing reason is kept. The result is the
``source = "ai"`` row of each segment. ``source = "user"`` rows are hard constraints: this
stage never writes, changes or deletes them (invariant 10), and ``effective`` reads them
first. Thresholds are first estimates, calibrated on the real corpus in M0 step 12.

Memory stays bounded: one asset at a time (invariant 13).
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.keys import artifact_key
from mosaic.core.time import parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import ResourceClass
from mosaic.jobs.registry import task
from mosaic.library import similarity as _similarity  # noqa: F401 - registers stages first
from mosaic.library import vision as _vision  # noqa: F401 - observations come from here
from mosaic.library.quality import shake_metric_name
from mosaic.library.segments import WOBBLE_FLOOR
from mosaic.media import inventory
from mosaic.storage import provenance
from mosaic.storage.models_project import (
    Asset,
    Disposition,
    SampleFrame,
    Segment,
    TechMetric,
    VisualObservation,
)

DISPOSITION_VERSION = "dispositions/2"  # AI "not usable" alone is MAYBE (ADR 0013 §5)
SEVERITY = {"USE": 0, "MAYBE": 1, "REJECT": 2}

MIN_USABLE = Fraction(7, 10)  # seconds of usable range
MIN_ASSET = Fraction(2)  # shorter recordings are accidental
BLACK_CLIP = 0.9  # median fraction of near-black pixels
DARK_MEAN = 25.0  # median luma (0..255)
OBSTRUCTED = 0.6  # median dark-and-flat fraction
FROZEN_REJECT = 0.8  # fraction of the usable range frozen
FROZEN_MAYBE = 0.3
SHAKE_PERCENTILE = 0.95
SHAKE_FACTOR = 3.0  # × the wobble floor, so a steady project has no "very shaky" shots
BLUR_PERCENTILE = 0.05
BLUR_VARIANCE = 15.0  # variance of the Laplacian at analysis width

AI_REJECT = {"accidental", "pocket_or_covered", "obstructed"}
AI_MAYBE = {
    "lens_dirty",
    "out_of_focus",
    "motion_blur",
    "shaky",
    "too_dark",
    "overexposed",
    "tilted",
    "nothing_happens",
}

CONFIG = {
    "min_usable": str(MIN_USABLE),
    "min_asset": str(MIN_ASSET),
    "black_clip": BLACK_CLIP,
    "dark_mean": DARK_MEAN,
    "obstructed": OBSTRUCTED,
    "frozen": [FROZEN_REJECT, FROZEN_MAYBE],
    "shake": [SHAKE_PERCENTILE, SHAKE_FACTOR],
    "blur": [BLUR_PERCENTILE, BLUR_VARIANCE],
    "ai_reject": sorted(AI_REJECT),
    "ai_maybe": sorted(AI_MAYBE),
}


@dataclass(frozen=True)
class Reason:
    code: str
    status: str  # MAYBE|REJECT
    source: str  # rule|ai
    detail: str = ""

    def as_json(self) -> dict[str, str]:
        out = {"code": self.code, "status": self.status, "source": self.source}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class SegmentFacts:
    """What the rules look at, for one segment (values over its usable range)."""

    usable_seconds: Fraction
    asset_seconds: Fraction
    clip_low: list[float]
    exposure: list[float]
    obstruction: list[float]
    sharpness: list[tuple[float, float | None]]  # (raw, percentile)
    shake: list[tuple[float, float | None]]
    shake_floor: float
    frozen_fraction: float


def _median(values: Iterable[float]) -> float | None:
    vals = list(values)
    return statistics.median(vals) if vals else None


def rule_reasons(f: SegmentFacts) -> list[Reason]:
    out: list[Reason] = []
    if f.asset_seconds < MIN_ASSET:
        out.append(Reason("accidental_recording", "REJECT", "rule"))
    if f.usable_seconds < MIN_USABLE:
        out.append(Reason("too_short", "REJECT", "rule"))
    black = _median(f.clip_low)
    if black is not None and black >= BLACK_CLIP:
        out.append(Reason("black_frames", "REJECT", "rule"))
    else:
        mean = _median(f.exposure)
        if mean is not None and mean < DARK_MEAN:
            out.append(Reason("too_dark", "MAYBE", "rule"))
    obstruction = _median(f.obstruction)
    if obstruction is not None and obstruction >= OBSTRUCTED:
        out.append(Reason("obstructed", "REJECT", "rule"))
    if f.frozen_fraction >= FROZEN_REJECT:
        out.append(Reason("frozen", "REJECT", "rule"))
    elif f.frozen_fraction >= FROZEN_MAYBE:
        out.append(Reason("partly_frozen", "MAYBE", "rule"))
    shake_p = _median(p for _, p in f.shake if p is not None)
    shake_v = _median(v for v, _ in f.shake)
    if (
        shake_p is not None
        and shake_v is not None
        and shake_p >= SHAKE_PERCENTILE
        and shake_v > SHAKE_FACTOR * f.shake_floor
    ):
        out.append(Reason("very_shaky", "MAYBE", "rule"))
    sharp_p = _median(p for _, p in f.sharpness if p is not None)
    sharp_v = _median(v for v, _ in f.sharpness)
    if (
        sharp_p is not None
        and sharp_v is not None
        and sharp_p <= BLUR_PERCENTILE
        and sharp_v < BLUR_VARIANCE
    ):
        out.append(Reason("blurry", "MAYBE", "rule"))
    return out


def ai_reasons(observation: dict[str, Any] | None) -> list[Reason]:
    if observation is None:
        return []
    out: list[Reason] = []
    if observation.get("usable") is False:
        # Without trip context the model calls content-poor views unusable that the story
        # may need (real Airshow footage: "blue sky with a tiny dark speck", the aircraft),
        # so on its own this is MAYBE; concrete issues below still REJECT.
        out.append(Reason("not_usable", "MAYBE", "ai", observation.get("description", "")))
    for issue in observation.get("issues", []):
        if issue in AI_REJECT:
            out.append(Reason(issue, "REJECT", "ai"))
        elif issue in AI_MAYBE:
            out.append(Reason(issue, "MAYBE", "ai"))
    if observation.get("interest") == "low" and observation.get("composition") == "poor":
        out.append(Reason("low_interest", "MAYBE", "ai"))
    return out


def decide(reasons: list[Reason]) -> str:
    return max((r.status for r in reasons), key=SEVERITY.__getitem__, default="USE")


def effective(session: Session, segment_ids: list[int]) -> dict[int, Disposition]:
    """The disposition in force per segment: the user's if there is one, else the AI's."""
    out: dict[int, Disposition] = {}
    for row in session.scalars(select(Disposition).where(Disposition.segment_id.in_(segment_ids))):
        assert row.segment_id is not None
        current = out.get(row.segment_id)
        if current is None or row.source == "user":
            out[row.segment_id] = row
    return out


# ------------------------------------------------------------------------ task


def segment_facts(session: Session, asset: Asset) -> dict[int, SegmentFacts]:
    assert asset.tb is not None
    tb = parse_rational(asset.tb)
    asset_seconds = Fraction(asset.duration_ticks or 0) * tb
    metrics = list(session.scalars(select(TechMetric).where(TechMetric.asset_id == asset.id)))
    sample_ticks = {
        sid: t
        for sid, t in session.execute(
            select(SampleFrame.id, SampleFrame.ticks).where(SampleFrame.asset_id == asset.id)
        )
    }
    shake_name = shake_metric_name({m.name for m in metrics})
    out: dict[int, SegmentFacts] = {}
    for seg in session.scalars(select(Segment).where(Segment.asset_id == asset.id)):
        a, b = seg.usable_start_ticks, seg.usable_end_ticks
        if b <= a:
            a, b = seg.start_ticks, seg.end_ticks
        at_sample: dict[str, list[TechMetric]] = {}
        in_range: dict[str, list[TechMetric]] = {}
        for m in metrics:
            if m.sample_id is not None:
                t = sample_ticks.get(m.sample_id, m.start_ticks)
                if a <= t < b:
                    at_sample.setdefault(m.name, []).append(m)
            elif m.start_ticks < b and m.end_ticks > a:
                in_range.setdefault(m.name, []).append(m)
        frozen = sum(
            min(b, m.end_ticks) - max(a, m.start_ticks) for m in in_range.get("freeze", [])
        )
        out[seg.id] = SegmentFacts(
            usable_seconds=Fraction(seg.usable_end_ticks - seg.usable_start_ticks) * tb,
            asset_seconds=asset_seconds,
            clip_low=[m.value for m in at_sample.get("clip_low", [])],
            exposure=[m.value for m in at_sample.get("exposure_mean", [])],
            obstruction=[m.value for m in at_sample.get("obstruction", [])],
            sharpness=[(m.value, m.percentile) for m in at_sample.get("sharpness", [])],
            shake=[(m.value, m.percentile) for m in in_range.get(shake_name, [])],
            shake_floor=WOBBLE_FLOOR[shake_name],
            frozen_fraction=frozen / (b - a) if b > a else 0.0,
        )
    return out


def _key(ctx: TaskContext) -> str:
    """Digest of every input, streamed: segments, observations and metric provenance."""
    h = hashlib.sha256()
    with ctx.project.db.session() as s:
        for row in s.execute(
            select(
                Segment.id,
                Segment.provenance_id,
                Segment.usable_start_ticks,
                Segment.usable_end_ticks,
            ).order_by(Segment.id)
        ):
            h.update(f"s{tuple(row)};".encode())
        for obs in s.execute(
            select(VisualObservation.segment_id, VisualObservation.provenance_id).order_by(
                VisualObservation.segment_id
            )
        ):
            h.update(f"v{tuple(obs)};".encode())
        for pid in s.scalars(
            select(TechMetric.provenance_id).distinct().order_by(TechMetric.provenance_id)
        ):
            h.update(f"m{pid};".encode())
    return artifact_key(
        "dispositions",
        project_id=ctx.project.id,
        inputs=h.hexdigest(),
        config=CONFIG,
        version=DISPOSITION_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("dispositions", _key(ctx))


@task("library.dispositions", is_done=_is_done)
def dispositions_task(ctx: TaskContext) -> dict[str, Any]:
    key = _key(ctx)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="dispositions",
                algorithm_version=DISPOSITION_VERSION,
                input_keys=[key],
                config_hash=key.rsplit("-", 1)[-1][:16],
            ),
        )
    with ctx.project.db.session() as s:
        asset_ids = list(
            s.scalars(select(Asset.id).where(Asset.kind == "video").order_by(Asset.id))
        )
    counts = {"USE": 0, "MAYBE": 0, "REJECT": 0}
    now = now_iso()
    for asset_id in asset_ids:
        ctx.check_cancelled()
        with ctx.project.db.session() as s:
            asset = s.get(Asset, asset_id)
            assert asset is not None
            facts = segment_facts(s, asset)
            segments = {
                g.id: (g.start_ticks, g.end_ticks)
                for g in s.scalars(select(Segment).where(Segment.asset_id == asset_id))
            }
            observations = {
                o.segment_id: o.data
                for o in s.scalars(
                    select(VisualObservation).where(
                        VisualObservation.segment_id.in_(list(segments))
                    )
                )
            }
        with ctx.write() as s:
            s.execute(
                delete(Disposition).where(
                    Disposition.asset_id == asset_id, Disposition.source == "ai"
                )
            )
            for seg_id, (a, b) in segments.items():
                reasons = rule_reasons(facts[seg_id]) + ai_reasons(observations.get(seg_id))
                status = decide(reasons)
                counts[status] += 1
                s.add(
                    Disposition(
                        asset_id=asset_id,
                        segment_id=seg_id,
                        anchor_start_ticks=a,
                        anchor_end_ticks=b,
                        source="ai",
                        status=status,
                        reasons=[r.as_json() for r in reasons],
                        roles=[],
                        provenance_id=prov,
                        updated_at=now,
                    )
                )
    ctx.project.artifacts.put_json("dispositions", key, counts, provenance_id=prov)
    return counts


inventory.PROJECT_STAGES.append(
    inventory.StageDef(
        "dispositions",
        "library.dispositions",
        ResourceClass.CPU,
        after=("normalize", "similarity"),
    )
)
