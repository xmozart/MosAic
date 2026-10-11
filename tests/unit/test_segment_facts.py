"""`segment_facts` indexes metrics by time (M2.11a): it must equal the plain scan it
replaced, on random segments, samples and metrics, including photo-like one-frame
segments and metrics on frame boundaries."""

from __future__ import annotations

import random
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.storage import provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, SampleFrame, Segment, Shot, TechMetric
from mosaic.storage.projects import init_project

NAMES = ("clip_low", "exposure_mean", "obstruction", "sharpness", "shake", "freeze")


def _reference(s: Any, asset: Asset) -> dict[int, dict[str, Any]]:
    """The scan before M2.11a: every segment against every metric of the asset."""
    metrics = list(
        s.scalars(select(TechMetric).where(TechMetric.asset_id == asset.id).order_by(TechMetric.id))
    )
    ticks = {
        sid: t
        for sid, t in s.execute(
            select(SampleFrame.id, SampleFrame.ticks).where(SampleFrame.asset_id == asset.id)
        )
    }
    out = {}
    for seg in s.scalars(select(Segment).where(Segment.asset_id == asset.id)):
        a, b = seg.usable_start_ticks, seg.usable_end_ticks
        if b <= a:
            a, b = seg.start_ticks, seg.end_ticks
        at: dict[str, list[Any]] = {}
        rng: dict[str, list[Any]] = {}
        for m in metrics:
            if m.sample_id is not None:
                t = ticks.get(m.sample_id, m.start_ticks)
                if a <= t < b or a == b == t:
                    at.setdefault(m.name, []).append((m.value, m.percentile))
            elif m.start_ticks < b and m.end_ticks > a:
                rng.setdefault(m.name, []).append(
                    (m.value, m.percentile, m.start_ticks, m.end_ticks)
                )
        out[seg.id] = {"at": at, "range": rng, "a": a, "b": b}
    return out


@pytest.mark.parametrize("seed", range(6))
def test_indexed_facts_equal_the_plain_scan(tmp_path: Path, seed: int) -> None:
    from mosaic.library.dispositions import metric_window, segment_facts, shake_percentiles
    from mosaic.library.quality import SHAKE_METRICS

    rnd = random.Random(seed)
    shake_name = "shake_gyro" if seed % 2 else "shake"  # telemetry clips: gyro shake
    names = tuple(shake_name if n == "shake" else n for n in NAMES)
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with p.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="t"))
        asset = Asset(
            kind="video",
            status="ok",
            profile="generic",
            group_key="k",
            created_at="x",
            provenance_id=prov,
            tb="1/1000",
            duration_ticks=60_000,
        )
        s.add(asset)
        s.flush()
        shot = Shot(
            asset_id=asset.id,
            index=0,
            start_ticks=0,
            end_ticks=60_000,
            method="t",
            provenance_id=prov,
        )
        s.add(shot)
        s.flush()
        bounds = sorted(rnd.sample(range(1, 60_000), 12))
        edges = [0, *bounds, 60_000]
        for k, (lo, hi) in enumerate(pairwise(edges)):
            us, ue = (lo, hi) if rnd.random() > 0.2 else (hi, hi)  # some empty usable ranges
            s.add(
                Segment(
                    asset_id=asset.id,
                    shot_id=shot.id,
                    index=k,
                    start_ticks=lo,
                    end_ticks=hi,
                    usable_start_ticks=us,
                    usable_end_ticks=ue,
                    provenance_id=prov,
                )
            )
        # A one-frame segment, as a photo has.
        s.add(
            Segment(
                asset_id=asset.id,
                shot_id=shot.id,
                index=99,
                start_ticks=0,
                end_ticks=0,
                usable_start_ticks=0,
                usable_end_ticks=0,
                provenance_id=prov,
            )
        )
        samples = []
        for t in sorted({0, *edges[:-1], *rnd.sample(range(60_000), 40)}):
            sf = SampleFrame(
                asset_id=asset.id,
                shot_id=shot.id,
                ticks=t,
                reason="interval",
                phash="0",
                provenance_id=prov,
            )
            s.add(sf)
            samples.append(sf)
        s.flush()
        for _ in range(400):
            name = rnd.choice(names)
            if name in (shake_name, "freeze"):
                lo = rnd.randrange(60_000)
                s.add(
                    TechMetric(
                        asset_id=asset.id,
                        start_ticks=lo,
                        end_ticks=min(60_000, lo + rnd.randrange(1, 4000)),
                        name=name,
                        value=rnd.random(),
                        percentile=rnd.random(),
                        provenance_id=prov,
                    )
                )
            else:
                sf = rnd.choice(samples)
                s.add(
                    TechMetric(
                        asset_id=asset.id,
                        sample_id=sf.id,
                        start_ticks=sf.ticks,
                        end_ticks=sf.ticks,
                        name=name,
                        value=rnd.random(),
                        percentile=rnd.choice([None, rnd.random()]),
                        provenance_id=prov,
                    )
                )
        # One range across the whole clip (it starts long before most segments) and an
        # empty one: the scan's window must not drop either (ADR 0063).
        for lo, hi in ((0, 60_000), (30_000, 30_000)):
            for name in (shake_name, "freeze"):
                s.add(
                    TechMetric(
                        asset_id=asset.id,
                        start_ticks=lo,
                        end_ticks=hi,
                        name=name,
                        value=rnd.random(),
                        percentile=rnd.random(),
                        provenance_id=prov,
                    )
                )
        if shake_name == "shake_gyro":
            # Optical shake beside the gyro's: both readers must ignore it.
            for lo in range(0, 60_000, 7_000):
                s.add(
                    TechMetric(
                        asset_id=asset.id,
                        start_ticks=lo,
                        end_ticks=lo + 3_000,
                        name="shake",
                        value=rnd.random(),
                        percentile=rnd.random(),
                        provenance_id=prov,
                    )
                )
    with p.db.session() as s:
        asset = s.scalars(select(Asset)).one()
        want = _reference(s, asset)
        got = segment_facts(s, asset)
        shake_only = segment_facts(s, asset, only=SHAKE_METRICS)
        loaded = list(s.scalars(select(Segment).where(Segment.asset_id == asset.id)))
        given = segment_facts(s, asset, only=SHAKE_METRICS, segments=loaded)
        # Retrieval's final candidates read only their shake percentiles (ADR 0065).
        windows = {
            asset.id: [
                (
                    g.id,
                    *metric_window(
                        g.start_ticks, g.end_ticks, g.usable_start_ticks, g.usable_end_ticks
                    ),
                )
                for g in loaded
            ]
        }
        few = shake_percentiles(s, windows)
    # Retrieval reads only shake: the same values, read from far fewer rows.
    assert {k: v.shake for k, v in shake_only.items()} == {k: v.shake for k, v in got.items()}
    assert given == shake_only  # with the segments retrieval already loaded
    assert {k: sorted(v) for k, v in few.items()} == {
        k: sorted(pc for _, pc in v.shake if pc is not None) for k, v in got.items()
    }
    assert all(not v.sharpness and not v.clip_low for v in shake_only.values())
    assert set(got) == set(want)
    for sid, w in want.items():
        g = got[sid]
        at, rng = w["at"], w["range"]
        assert g.clip_low == [v for v, _ in at.get("clip_low", [])]
        assert g.exposure == [v for v, _ in at.get("exposure_mean", [])]
        assert g.obstruction == [v for v, _ in at.get("obstruction", [])]
        assert g.sharpness == at.get("sharpness", [])
        assert g.shake == [(v, pc) for v, pc, _, _ in rng.get(shake_name, [])]
        a, b = w["a"], w["b"]
        frozen = sum(min(b, e) - max(a, st) for _, _, st, e in rng.get("freeze", []))
        assert g.frozen_fraction == (frozen / (b - a) if b > a else 0.0)
        assert g.asset_seconds == Fraction(60)
    p.close()
