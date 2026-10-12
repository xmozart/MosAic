"""Retrieval reads clips in batches and describes only its final candidates (ADR 0065):
it must equal the clip-at-a-time reading it replaced, across batch boundaries and the
cap, with the owner's decisions, observations and reviews, speech and shake."""

from __future__ import annotations

import random
import statistics
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.editing import retrieval
from mosaic.editing.categories import classify
from mosaic.editing.retrieval import Candidate, cap_by_day, capture_dates, trip_day
from mosaic.library import decisions
from mosaic.library.dispositions import segment_facts
from mosaic.library.quality import SHAKE_METRICS
from mosaic.storage import provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import (
    Asset,
    ClipDecision,
    DeepReview,
    Disposition,
    Mosaic,
    Segment,
    Shot,
    SimilarityGroup,
    TechMetric,
    TranscriptSegment,
    VisualObservation,
)
from mosaic.storage.projects import Project, init_project

T = "2026-07-15T09:00:00+00:00"
SEC = 1000  # ticks per second at 1/1000
CLIPS = 7
SEGMENTS = 5  # of 4 s each


def _build(tmp_path: Path) -> Project:
    rnd = random.Random(7)
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with p.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        group = SimilarityGroup(method="embedding", size=3, provenance_id=prov)
        s.add(group)
        s.flush()
        for n in range(CLIPS):
            a = Asset(
                kind="video",
                status="ok",
                profile="generic",
                group_key=f"c{n}",
                capture_time=f"2026-07-{15 + n % 3}T09:{n:02d}:00+00:00",
                tb="1/1000",
                rate="30/1",
                duration_ticks=SEGMENTS * 4 * SEC,
                provenance_id=prov,
                created_at=T,
            )
            s.add(a)
            s.flush()
            shot = Shot(
                asset_id=a.id,
                index=0,
                start_ticks=0,
                end_ticks=SEGMENTS * 4 * SEC,
                method="adaptive",
                provenance_id=prov,
            )
            s.add(shot)
            s.flush()
            for i in range(SEGMENTS):
                lo = i * 4 * SEC
                short = rnd.random() < 0.15  # a usable range under the minimum
                g = Segment(
                    asset_id=a.id,
                    shot_id=shot.id,
                    index=i,
                    start_ticks=lo,
                    end_ticks=lo + 4 * SEC,
                    usable_start_ticks=lo + 100,
                    usable_end_ticks=lo + (600 if short else 3_900),
                    has_speech=n % 2 == 0 and i % 2 == 0,
                    quality=round(rnd.random(), 3),
                    similarity_group_id=group.id if i == 4 and n < 3 else None,
                    group_best=i == 4 and n == 0,
                    provenance_id=prov,
                )
                s.add(g)
                s.flush()
                s.add(
                    Disposition(
                        asset_id=a.id,
                        segment_id=g.id,
                        anchor_start_ticks=g.start_ticks,
                        anchor_end_ticks=g.end_ticks,
                        source="ai",
                        status=rnd.choice(["USE", "USE", "MAYBE", "REJECT"]),
                        reasons=[{"issue": "test"}],
                        updated_at=T,
                        provenance_id=prov,
                    )
                )
                if rnd.random() < 0.2:  # the owner's own decision on the segment
                    s.add(
                        Disposition(
                            asset_id=a.id,
                            segment_id=g.id,
                            anchor_start_ticks=g.start_ticks,
                            anchor_end_ticks=g.end_ticks,
                            source="user",
                            status=rnd.choice(["USE", "REJECT"]),
                            updated_at=T,
                            provenance_id=prov,
                        )
                    )
                if rnd.random() < 0.6:
                    sheet = Mosaic(
                        asset_id=a.id,
                        index=g.id,
                        image_key=f"k{g.id}",
                        cols=4,
                        rows=4,
                        tile_width=1,
                        tile_height=1,
                        provenance_id=prov,
                    )
                    s.add(sheet)
                    s.flush()
                    s.add(
                        VisualObservation(
                            segment_id=g.id,
                            mosaic_id=sheet.id,
                            data={
                                "interest": rnd.choice(["low", "medium", "high"]),
                                "composition": rnd.choice(["poor", "good", "excellent"]),
                                "description": f"L2 {g.id}",
                            },
                            provenance_id=prov,
                        )
                    )
                    if rnd.random() < 0.3:  # L3 supersedes it
                        s.add(
                            DeepReview(
                                segment_id=g.id,
                                key=f"r{g.id}",
                                data={"interest": "high", "description": f"L3 {g.id}"},
                                context_digest="d",
                                provenance_id=prov,
                            )
                        )
            # Shake per second; clip 2 has gyro beside optical, so gyro is read.
            for name in ("shake_gyro", "shake") if n == 2 else ("shake",):
                for sec in range(SEGMENTS * 4):
                    s.add(
                        TechMetric(
                            asset_id=a.id,
                            start_ticks=sec * SEC,
                            end_ticks=(sec + 1) * SEC,
                            name=name,
                            value=rnd.random(),
                            percentile=None if rnd.random() < 0.1 else rnd.random(),
                            provenance_id=prov,
                        )
                    )
            if n % 2 == 0:
                for k in range(SEGMENTS * 2):
                    s.add(
                        TranscriptSegment(
                            asset_id=a.id,
                            start_ticks=k * 2 * SEC,
                            end_ticks=k * 2 * SEC + 1_500,
                            text=f" words {n}.{k} " if k % 3 else "  ",
                            provenance_id=prov,
                        )
                    )
        rules = {1: ("never", None), 3: ("always", None), 5: (None, "REJECT")}
        for n, (include, disposition) in rules.items():
            aid = s.scalars(select(Asset.id).where(Asset.group_key == f"c{n}")).one()
            s.add(
                ClipDecision(asset_id=aid, include=include, disposition=disposition, updated_at=T)
            )
    return p


def _reference(
    s: Any, min_seconds: Fraction, want_seconds: Fraction
) -> tuple[list[Candidate], dict[str, int]]:
    """Clip-at-a-time retrieval, as before ADR 0065."""
    counts = {"segments": 0, "rejected": 0, "too_short": 0, "duplicate": 0, "analysis_only": 0}
    found: list[Candidate] = []
    similar: list[Candidate] = []
    best_of = {
        gid: sid
        for sid, gid in s.execute(
            select(Segment.id, Segment.similarity_group_id).where(Segment.group_best.is_(True))
        )
        if gid is not None
    }
    assets = list(s.scalars(select(Asset).where(Asset.kind == "video").order_by(Asset.id)))
    first_day = min(capture_dates(assets).values(), default=None)
    for asset in assets:
        tb = Fraction(1, 1000)
        segs = list(s.scalars(select(Segment).where(Segment.asset_id == asset.id)))
        ids = [g.id for g in segs]
        disp = decisions.for_segments(s, asset, segs)
        obs = {
            o.segment_id: o.data
            for o in s.scalars(
                select(VisualObservation).where(VisualObservation.segment_id.in_(ids))
            )
        }
        obs |= {
            r.segment_id: r.data
            for r in s.scalars(select(DeepReview).where(DeepReview.segment_id.in_(ids)))
        }
        facts = segment_facts(s, asset, only=SHAKE_METRICS, segments=segs)
        base = retrieval._capture(asset)
        for g in segs:
            counts["segments"] += 1
            d = disp.get(g.id)
            status = (d.status if d else None) or "USE"
            user_use = bool(d and d.forced)
            if status == "REJECT":
                counts["rejected"] += 1
                continue
            if (
                Fraction(g.usable_end_ticks - g.usable_start_ticks) * tb < min_seconds
                and not user_use
            ):
                counts["too_short"] += 1
                continue
            duplicate = g.similarity_group_id is not None and not g.group_best and not user_use
            shake = [pc for _, pc in facts[g.id].shake if pc is not None]
            words = s.scalars(
                select(TranscriptSegment.text)
                .where(
                    TranscriptSegment.asset_id == asset.id,
                    TranscriptSegment.start_ticks < g.usable_end_ticks,
                    TranscriptSegment.end_ticks > g.usable_start_ticks,
                )
                .order_by(TranscriptSegment.start_ticks)
            )
            text = " ".join(t.strip() for t in words if t.strip())[: retrieval.TRANSCRIPT_CHARS]
            (similar if duplicate else found).append(
                Candidate(
                    segment_id=g.id,
                    asset_id=asset.id,
                    shot_id=g.shot_id,
                    tb=asset.tb or "",
                    rate=asset.rate,
                    start=g.start_ticks,
                    end=g.end_ticks,
                    usable_start=g.usable_start_ticks,
                    usable_end=g.usable_end_ticks,
                    has_speech=g.has_speech,
                    status="USE" if status == "USE" else "MAYBE",
                    user_use=user_use,
                    capture=base + timedelta(seconds=float(Fraction(g.start_ticks) * tb))
                    if base
                    else None,
                    day=trip_day(asset.capture_time, Fraction(g.start_ticks) * tb, first_day),
                    quality=g.quality,
                    group_id=g.similarity_group_id,
                    shake_percentile=statistics.median(shake) if shake else None,
                    transcript=text if g.has_speech else "",
                    obs=obs.get(g.id, {}),
                    similar_to=best_of.get(g.similarity_group_id or -1) if duplicate else None,
                    categories=classify(
                        obs.get(g.id, {}), has_speech=g.has_speech, rate=asset.rate
                    ),
                )
            )
    counts["duplicate"] = len(similar)
    if sum((c.usable_seconds for c in found), Fraction(0)) < 3 * want_seconds:
        found += similar
        counts["duplicate_fallback"] = len(similar)
    capped = cap_by_day(found, retrieval.MAX_CANDIDATES)
    counts["candidates"] = len(capped)
    counts["capped"] = len(found) - len(capped)
    return sorted(capped, key=Candidate.sort_key), counts


@pytest.mark.parametrize(("cap", "want"), [(200, 10), (6, 10), (6, 10_000)])
def test_batched_retrieval_equals_clip_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: int, want: int
) -> None:
    project = _build(tmp_path)
    monkeypatch.setattr(retrieval, "CLIP_BATCH", 2)  # batch edges inside the trip
    monkeypatch.setattr(retrieval, "MAX_CANDIDATES", cap)
    with project.db.session() as s:
        expected = _reference(s, Fraction(1), Fraction(want))
    with project.db.session() as s:
        got = retrieval.retrieve(s, Fraction(1), Fraction(want))
    assert got[1] == expected[1]
    assert [vars(c) for c in got[0]] == [vars(c) for c in expected[0]]
    # The fixture exercises what it claims to.
    cands = got[0]
    assert any(c.transcript for c in cands)
    assert any(c.shake_percentile is not None for c in cands)
    assert any(c.obs.get("description", "").startswith("L3") for c in cands) or cap < 200
    assert got[1]["rejected"] > 0
    with project.db.session() as s:
        gyro = s.scalars(select(Asset.id).where(Asset.group_key == "c2")).one()
    assert any(c.asset_id == gyro and c.shake_percentile is not None for c in cands)
    project.close()


def test_content_weights_rank_and_avoid(tmp_path: Path) -> None:
    project = _build(tmp_path)
    with project.write() as s:  # the owner keeps one speech segment: USE
        seg = s.scalars(
            select(Segment).where(Segment.has_speech.is_(True)).order_by(Segment.id)
        ).first()
        assert seg is not None
        for row in s.scalars(select(Disposition).where(Disposition.segment_id == seg.id)):
            s.delete(row)
        s.flush()
        s.add(
            Disposition(
                asset_id=seg.asset_id,
                segment_id=seg.id,
                anchor_start_ticks=seg.start_ticks,
                anchor_end_ticks=seg.end_ticks,
                source="user",
                status="USE",
                updated_at=T,
                provenance_id=seg.provenance_id,
            )
        )
        picked = seg.id
        locked = s.scalars(
            select(Segment.id).where(Segment.has_speech.is_(True), Segment.id != picked)
        ).first()
    with project.db.session() as s:
        plain, plain_counts = retrieval.retrieve(s, Fraction(1), Fraction(10))
        weighted, counts = retrieval.retrieve(
            s, Fraction(1), Fraction(10), {"conversations": "avoid"}
        )
        liked, _ = retrieval.retrieve(s, Fraction(1), Fraction(10), {"conversations": "strong"})
    speech = [c for c in plain if "conversations" in c.categories]
    assert speech, "the fixture has speech"
    kept = [c for c in weighted if "conversations" in c.categories]
    assert [c.segment_id for c in kept] == [picked], "avoided unless the owner picked it"
    assert kept[0].user_use
    # Counted before near-duplicates and the cap, so at least those the plain list had.
    assert counts["avoided"] >= len([c for c in speech if not c.user_use]) > 0
    assert "avoided" not in plain_counts
    assert all(c.bonus == 0.0 for c in plain)
    assert all(c.bonus == 2.0 for c in liked if "conversations" in c.categories)
    with project.db.session() as s:  # a locked shot's segment is never avoided
        held, _ = retrieval.retrieve(
            s, Fraction(1), Fraction(10_000), {"conversations": "avoid"}, frozenset({locked})
        )
    assert locked in {c.segment_id for c in held}
    project.close()


def test_photos_by_share_with_bursts_and_capture_twins(tmp_path: Path) -> None:
    """ADR 0075: photos are candidates unless the share is "none"; a burst gives only
    its best frame; a photo of a moment that also has video is that video's look-alike;
    "many" ranks photos up."""
    from mosaic.storage.models_project import PhotoGroup, PhotoGroupMember

    project = _build(tmp_path)
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="photos"))
        ids = []
        for n in range(4):
            a = Asset(
                kind="photo",
                status="ok",
                profile="generic",
                group_key=f"p{n}",
                capture_time=f"2026-07-15T09:{20 + n:02d}:00+00:00",
                tb="1/1",
                duration_ticks=0,
                provenance_id=prov,
                created_at=T,
            )
            s.add(a)
            s.flush()
            sh = Shot(
                asset_id=a.id,
                index=0,
                start_ticks=0,
                end_ticks=0,
                method="photo",
                provenance_id=prov,
            )
            s.add(sh)
            s.flush()
            g = Segment(
                asset_id=a.id,
                shot_id=sh.id,
                index=0,
                start_ticks=0,
                end_ticks=0,
                usable_start_ticks=0,
                usable_end_ticks=0,
                provenance_id=prov,
            )
            s.add(g)
            s.flush()
            ids.append(g.id)
        burst = PhotoGroup(kind="burst", best_segment_id=ids[1], provenance_id=prov)
        capture = PhotoGroup(kind="capture", provenance_id=prov)
        s.add_all([burst, capture])
        s.flush()
        video_seg = s.scalars(
            select(Segment.id)
            .join(Asset, Asset.id == Segment.asset_id)
            .where(Asset.kind == "video")
            .order_by(Segment.id)
        ).first()
        s.add_all(
            [
                PhotoGroupMember(group_id=burst.id, segment_id=ids[0]),
                PhotoGroupMember(group_id=burst.id, segment_id=ids[1]),
                PhotoGroupMember(group_id=capture.id, segment_id=ids[3]),
                PhotoGroupMember(group_id=capture.id, segment_id=video_seg),
            ]
        )
    with project.db.session() as s:
        none, _ = retrieval.retrieve(s, Fraction(1), Fraction(10_000))
        some, counts = retrieval.retrieve(s, Fraction(1), Fraction(10_000), photo_share="some")
        many, _ = retrieval.retrieve(s, Fraction(1), Fraction(10_000), photo_share="many")
    assert not any(c.still for c in none)
    stills = {c.segment_id: c for c in some if c.still}
    assert ids[0] not in stills, "a burst gives only its best frame"
    assert counts["burst"] == 1
    assert {ids[1], ids[2], ids[3]} <= set(stills), "the twin comes back in the fallback"
    assert stills[ids[3]].similar_to == video_seg, "a look-alike of its video"
    assert stills[ids[1]].similar_to is None
    assert all(c.bonus == 0 for c in stills.values())
    assert all(c.bonus == 1.0 for c in many if c.still), "many ranks photos up"
    assert all("photos" in c.categories for c in stills.values())
    # A storyboard's lock keeps a burst's other frame and a twin as candidates in their
    # own right (invariant 10).
    with project.db.session() as s:
        held, _ = retrieval.retrieve(
            s, Fraction(1), Fraction(10_000), keep=frozenset({ids[0], ids[3]}), photo_share="some"
        )
    by_id = {c.segment_id: c for c in held}
    assert ids[0] in by_id, "a locked burst frame stays"
    assert by_id[ids[3]].similar_to is None, "a locked twin is no look-alike"
    project.close()


def test_some_photos_never_crowd_out_the_video() -> None:
    def cand(n: int, still: bool, user: bool = False) -> Candidate:
        return Candidate(
            segment_id=n,
            asset_id=n,
            shot_id=n,
            tb="1/1" if still else "1/1000",
            rate=None,
            start=0,
            end=0 if still else 4000,
            usable_start=0,
            usable_end=0 if still else 4000,
            has_speech=False,
            status="USE",
            user_use=user,
            capture=None,
            day=1,
            quality=n / 1000,
            group_id=None,
            shake_percentile=None,
            still=still,
        )

    photos = [cand(n, True) for n in range(1, 101)] + [cand(500, True, user=True)]
    videos = [cand(n, False) for n in range(1000, 1010)]
    counts: dict[str, int] = {}
    kept = retrieval.cap_stills(photos + videos, "some", frozenset({1}), counts)
    stills = [c for c in kept if c.still]
    assert len([c for c in stills if not c.user_use and c.segment_id != 1]) == 50
    assert {1, 500} <= {c.segment_id for c in stills}, "locks and the owner's picks stay"
    assert counts["photos_capped"] == 49
    assert len([c for c in kept if not c.still]) == 10
    assert retrieval.cap_stills(photos, "many", frozenset(), {}) == photos


def test_a_photo_before_the_first_video_never_renumbers_the_trip(tmp_path: Path) -> None:
    """Day 1 is the first video's date everywhere (ADR 0075): an earlier photo is day 0,
    and the videos' days are the same whatever the photo share."""
    project = _build(tmp_path)
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="photos"))
        a = Asset(
            kind="photo",
            status="ok",
            profile="generic",
            group_key="early",
            capture_time="2026-07-14T08:00:00+00:00",
            tb="1/1",
            duration_ticks=0,
            provenance_id=prov,
            created_at=T,
        )
        s.add(a)
        s.flush()
        sh = Shot(
            asset_id=a.id, index=0, start_ticks=0, end_ticks=0, method="photo", provenance_id=prov
        )
        s.add(sh)
        s.flush()
        s.add(
            Segment(
                asset_id=a.id,
                shot_id=sh.id,
                index=0,
                start_ticks=0,
                end_ticks=0,
                usable_start_ticks=0,
                usable_end_ticks=0,
                provenance_id=prov,
            )
        )
    with project.db.session() as s:
        none, _ = retrieval.retrieve(s, Fraction(1), Fraction(10_000))
        some, _ = retrieval.retrieve(s, Fraction(1), Fraction(10_000), photo_share="some")
    days = {c.segment_id: c.day for c in none}
    assert {c.segment_id: c.day for c in some if not c.still} == days
    assert min(days.values()) == 1
    assert [c.day for c in some if c.still] == [0]
    project.close()
