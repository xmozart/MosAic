"""S11 Clip detail: everything about one clip and the AI's reasoning (API_MAP; ADR 0043).

Read per clip, never per project (invariant 13): the clip's segments, observations,
decisions and metrics, plus a few aggregate queries for its position and the edits that use
it. Times are exact ``{ticks, tb}`` in the clip's logical time base; quality words compare
the clip with the rest of the trip (the metrics' percentiles).
"""

from __future__ import annotations

import statistics
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from mosaic.core.time import parse_rational
from mosaic.library import browse, decisions
from mosaic.library.quality import shake_metric_name
from mosaic.storage.models_project import (
    Asset,
    ClipDecision,
    DeepReview,
    Device,
    Disposition,
    MediaFile,
    PhotoGroup,
    PhotoGroupMember,
    SampleFrame,
    Segment,
    Sidecar,
    TechMetric,
    TranscriptSegment,
    TranscriptWord,
    VisualObservation,
)

# Disposition reason codes in the owner's words (VOICE.md): rules and vision issues.
REASON_WORDS = {
    "accidental_recording": "Looks like an accidental recording",
    "too_short": "Too short to use",
    "black_frames": "Mostly black",
    "too_dark": "Too dark",
    "obstructed": "Something blocks the view",
    "frozen": "The picture is frozen",
    "partly_frozen": "Partly frozen",
    "very_shaky": "Very shaky",
    "blurry": "Blurry",
    "accidental": "Looks accidental",
    "pocket_or_covered": "Lens covered",
    "lens_dirty": "Dirty lens",
    "out_of_focus": "Out of focus",
    "motion_blur": "Motion blur",
    "shaky": "Shaky",
    "overexposed": "Overexposed",
    "tilted": "Tilted",
    "nothing_happens": "Nothing much happens",
    "low_interest": "Not much of interest",
    "not_usable": "The AI found nothing usable",
    "clip_rejected": "You rejected the whole clip",
}
QUALITY_METRICS = (
    "sharpness",
    "shake",
    "shake_gyro",
    "exposure_mean",
    "clip_low",
    "clip_high",
    "lufs_integrated",
    "wind",
)
TRANSCRIPT_PAGE = 200


def reason_words(reasons: list[Any]) -> list[str]:
    out = []
    for r in reasons or []:
        code = r.get("code") if isinstance(r, dict) else None
        if code:
            words = REASON_WORDS.get(code, code.replace("_", " ").capitalize())
            if words not in out:
                out.append(words)
    return out


def _grade(score: float | None) -> str | None:
    """0–1, higher is better: under 0.25 Poor, under 0.5 Fair, under 0.85 Good, else
    Excellent."""
    if score is None:
        return None
    if score >= 0.85:
        return "Excellent"
    return "Good" if score >= 0.5 else "Fair" if score >= 0.25 else "Poor"


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def grades(
    by: dict[str, list[tuple[float, float | None]]], has_audio: bool
) -> dict[str, str | None]:
    """Quality words from a clip's metrics (name → [(value, percentile)]): heuristics for
    M2 (ADR 0043). Sharpness and steadiness against the trip's percentiles; exposure by
    the mean level (0–255) against mid-grey, less clipping; audio by integrated loudness,
    less wind where there is no speech."""
    sharp = _median([p for _, p in by.get("sharpness", []) if p is not None])
    shake_name = shake_metric_name(set(by))
    shake = _median([p for _, p in by.get(shake_name, []) if p is not None])
    level = _median([v for v, _ in by.get("exposure_mean", [])])
    clipped = _median(
        [v for v, _ in by.get("clip_low", [])] + [v for v, _ in by.get("clip_high", [])]
    )
    exposure: float | None = None
    if level is not None:
        mean = level / 255.0
        exposure = max(0.0, 1.0 - abs(mean - 0.45) / 0.45 - (clipped or 0.0))
    audio: float | None = None
    if has_audio and by.get("lufs_integrated"):
        lufs = by["lufs_integrated"][0][0]
        audio = max(0.0, min(1.0, (lufs + 50) / 30))  # -50 LUFS → 0, -20 → 1
        if not by.get("speech"):
            wind = _median([v for v, _ in by.get("wind", [])]) or 0.0
            audio = max(0.0, audio - wind * 0.5)
    return {
        "sharpness": _grade(sharp),
        "steadiness": _grade(None if shake is None else 1 - shake),
        "exposure": _grade(exposure),
        "audio": _grade(audio),
    }


def quality(s: Session, asset_id: int, has_audio: bool, has_speech: bool) -> dict[str, str | None]:
    by: dict[str, list[tuple[float, float | None]]] = {}
    for name, value, pct in s.execute(
        select(TechMetric.name, TechMetric.value, TechMetric.percentile).where(
            TechMetric.asset_id == asset_id,
            TechMetric.name.in_(QUALITY_METRICS),
        )
    ):
        by.setdefault(name, []).append((value, pct))
    if has_speech:
        by["speech"] = [(1.0, None)]  # voices are low-frequency energy, not wind
    return grades(by, has_audio)


def _badges(s: Session, a: Asset) -> list[str]:
    out: list[str] = []
    if a.color_hint in ("hlg", "pq"):
        out.append("HDR")
    elif a.color_hint == "log":
        out.append("Log")
    h = min(a.display_width or 0, a.display_height or 0) if a.display_width else 0
    if a.kind == "video" and h:
        res = (
            "4K"
            if h >= 2160
            else "2.7K"
            if h >= 1520
            else "1080p"
            if h >= 1080
            else "720p"
            if h >= 720
            else f"{h}p"
        )
        fps = round(float(parse_rational(a.rate))) if a.rate else None
        out.append(f"{res} {fps}" if fps else res)
    if a.kind == "live_photo":
        out.append("Live Photo")
    if "analysis_only" in (a.flags or []):
        out.append("360")
    has_telemetry = s.scalar(
        select(func.count(Sidecar.id))
        .join(MediaFile, Sidecar.owner_media_file_id == MediaFile.id)
        .where(MediaFile.asset_id == a.id, Sidecar.kind == "srt", Sidecar.status == "valid")
    )
    if has_telemetry:
        out.append("Telemetry")
    return out


def _time(ticks: int, tb: str | None) -> dict[str, Any] | None:
    return {"ticks": ticks, "tb": tb} if tb else None


def _position(s: Session, a: Asset, show_rejected: bool, rejected: bool) -> dict[str, Any] | None:
    """The clip's place in its day as the library lists it, and its neighbours across days.
    ``None`` for a clip the grid does not show (unsupported); a rejected clip counts among
    rejected clips even when the grid hides them."""
    if not browse.shown(a):
        return None
    st = browse.status_table()
    f = browse.Filters(show_rejected=show_rejected or rejected)
    t = func.coalesce(Asset.capture_time, browse.UNKNOWN_TIME)
    key = (a.capture_time or browse.UNKNOWN_TIME, a.id)
    day = key[0][:10] if a.capture_time else browse.UNKNOWN_TIME
    base = browse.filtered(select(Asset.id).select_from(Asset), f, st)
    prev_id = s.scalar(
        base.where(tuple_(t, Asset.id) < key).order_by(t.desc(), Asset.id.desc()).limit(1)
    )
    next_id = s.scalar(base.where(tuple_(t, Asset.id) > key).order_by(t, Asset.id).limit(1))
    in_day = browse.filtered(select(func.count(Asset.id)).select_from(Asset), f, st).where(
        func.substr(t, 1, 10) == day
    )
    count = s.scalar(in_day) or 0
    index = (s.scalar(in_day.where(tuple_(t, Asset.id) < key)) or 0) + 1
    known = day != browse.UNKNOWN_TIME
    return {
        "day": browse.day_numbers(s).get(day) if known else None,
        "date": day if known else None,
        "index": index,
        "count": count,
        "prev": prev_id,
        "next": next_id,
    }


def _used_in(s: Session, asset_id: int) -> list[dict[str, Any]]:
    """Edits whose latest version cuts this clip: an exact match on the events' asset id."""
    from sqlalchemy import text

    rows = s.execute(
        text(
            """
            SELECT e.uid, e.name, v.version
            FROM edit e
            JOIN edit_version v ON v.edit_id = e.id
            WHERE v.version = (SELECT max(version) FROM edit_version w WHERE w.edit_id = e.id)
              AND EXISTS (
                SELECT 1 FROM json_each(v.timeline, '$.tracks[0].events') ev
                WHERE json_extract(ev.value, '$.asset_id') = :ref
              )
            ORDER BY e.created_at DESC
            """
        ),
        {"ref": f"ast_{asset_id:04d}"},
    )
    return [{"edit_id": uid, "name": name, "version": v} for uid, name, v in rows]


def _similar(s: Session, segment_ids: list[int], asset_id: int) -> list[dict[str, Any]]:
    groups = select(Segment.similarity_group_id).where(
        Segment.id.in_(segment_ids), Segment.similarity_group_id.is_not(None)
    )
    rows = s.execute(
        select(Segment.asset_id, func.min(SampleFrame.id))
        .join(SampleFrame, (SampleFrame.asset_id == Segment.asset_id) & SampleFrame.kept.is_(True))
        .where(Segment.similarity_group_id.in_(groups), Segment.asset_id != asset_id)
        .group_by(Segment.asset_id)
        .order_by(Segment.asset_id)
        .limit(12)
    )
    return [{"asset_id": aid, "sample_id": sid} for aid, sid in rows]


def _burst(s: Session, segment_ids: list[int]) -> dict[str, Any] | None:
    group = s.scalar(
        select(PhotoGroup)
        .join(PhotoGroupMember, PhotoGroupMember.group_id == PhotoGroup.id)
        .where(PhotoGroupMember.segment_id.in_(segment_ids), PhotoGroup.kind == "burst")
        .order_by(PhotoGroup.id)
        .limit(1)
    )
    if group is None:
        return None
    members = s.execute(
        select(Segment.id, Segment.asset_id, func.min(SampleFrame.id))
        .join(PhotoGroupMember, PhotoGroupMember.segment_id == Segment.id)
        .outerjoin(
            SampleFrame, (SampleFrame.asset_id == Segment.asset_id) & SampleFrame.kept.is_(True)
        )
        .where(PhotoGroupMember.group_id == group.id)
        .group_by(Segment.id, Segment.asset_id)
        .order_by(Segment.asset_id)
    )
    return {
        "items": [
            {"asset_id": aid, "sample_id": sid, "best": seg == group.best_segment_id}
            for seg, aid, sid in members
        ]
    }


def _ai_rows(s: Session, ids: list[int]) -> dict[int, Disposition]:
    return {
        d.segment_id: d
        for d in s.scalars(
            select(Disposition).where(Disposition.segment_id.in_(ids), Disposition.source == "ai")
        )
        if d.segment_id is not None
    }


def _tile_status(
    ruled: dict[int, decisions.SegmentDecision], clip: ClipDecision | None
) -> tuple[str | None, bool]:
    """The status the library tile shows and whether the analysis set it: the best of the
    segments, the owner's when tied (``browse.status_table`` states the same rule)."""
    rank = browse.PRIORITY
    decided = [(rank[d.status], d.source) for d in ruled.values() if d.status]
    if not decided:
        rule = decisions.clip_rule(clip)
        return rule, False
    best = min(r for r, _ in decided)
    owners = any(r == best and src in ("user", "clip") for r, src in decided)
    return browse.STATUS_OF[best], not owners


def clip_detail(s: Session, asset_id: int, show_rejected: bool = False) -> dict[str, Any]:
    a = s.get(Asset, asset_id)
    if a is None:
        raise LookupError(asset_id)
    names = list(
        s.scalars(
            # The first path, as the library names a clip (``browse.page``).
            select(MediaFile.rel_path)
            .where(MediaFile.asset_id == a.id)
            .order_by(MediaFile.rel_path)
        )
    )
    device = s.get(Device, a.device_id) if a.device_id else None
    segs = list(
        s.scalars(select(Segment).where(Segment.asset_id == a.id).order_by(Segment.start_ticks))
    )
    ids = [g.id for g in segs]
    ruled = decisions.for_segments(s, a, segs) if segs else {}
    obs = {
        o.segment_id: o.data
        for o in s.scalars(select(VisualObservation).where(VisualObservation.segment_id.in_(ids)))
    }
    obs |= {
        r.segment_id: r.data
        for r in s.scalars(select(DeepReview).where(DeepReview.segment_id.in_(ids)))
    }
    # The analysis's own view, beside the decision in force (the AI-vs-you line, S11).
    ai_only = _ai_rows(s, ids)
    best_sample = dict(
        s.execute(
            select(SampleFrame.shot_id, func.min(SampleFrame.id))
            .where(SampleFrame.asset_id == a.id, SampleFrame.kept.is_(True))
            .group_by(SampleFrame.shot_id)
        ).all()
    )
    moments = []
    for g in segs:
        d = ruled.get(g.id)
        o = obs.get(g.id) or {}
        ai = ai_only.get(g.id)
        moments.append(
            {
                "segment_id": g.id,
                "start": _time(g.start_ticks, a.tb),
                "end": _time(g.end_ticks, a.tb),
                "usable_start": _time(g.usable_start_ticks, a.tb),
                "usable_end": _time(g.usable_end_ticks, a.tb),
                "status": d.status if d else None,
                "decided_by": d.source if d else None,  # user | clip | ai | None
                "ai_status": ai.status if ai else None,
                "description": o.get("description"),
                "interest": o.get("interest"),
                "reasons": reason_words(list(ai.reasons) if ai else []),
                "has_speech": g.has_speech,
                "sample_id": best_sample.get(g.shot_id),
            }
        )
    # The "Why": the analysis's description of the clip's best moment, and its reasons.
    best = max(
        (m for m in moments if m["ai_status"]),
        key=lambda m: ({"USE": 2, "MAYBE": 1}.get(str(m["ai_status"]), 0), m["interest"] == "high"),
        default=None,
    )
    ai_status = None
    if ai_only:
        ai_status = min((d.status for d in ai_only.values()), key=lambda st: browse.PRIORITY[st])
    clip = s.get(ClipDecision, a.id)
    shown, by_ai = _tile_status(ruled, clip)
    sentences = s.scalar(
        select(func.count(TranscriptSegment.id)).where(TranscriptSegment.asset_id == a.id)
    )
    language = s.scalar(
        select(TranscriptSegment.language)
        .where(TranscriptSegment.asset_id == a.id, TranscriptSegment.language.is_not(None))
        .group_by(TranscriptSegment.language)
        .order_by(func.count().desc())
        .limit(1)
    )
    tags = decisions.tags(s, [a.id]).get(a.id, [])
    return {
        "asset_id": a.id,
        "kind": a.kind,
        "status": a.status,
        "name": names[0].rsplit("/", 1)[-1] if names else None,
        "files": len(names),
        "reason": a.reason,
        "fix": a.suggested_fix,
        "camera": (device.label if device else None) or a.camera_model or a.profile.title(),
        "capture_time": a.capture_time,
        "duration": _time(a.duration_ticks, a.tb) if a.duration_ticks is not None else None,
        "rate": a.rate,
        "width": a.display_width,
        "height": a.display_height,
        "badges": _badges(s, a),
        "analysis_only": "analysis_only" in (a.flags or []),
        "position": _position(s, a, show_rejected, shown == "REJECT"),
        "status_shown": shown,
        "decided_by": (("ai" if by_ai else "user") if shown else None),
        "ai_status": ai_status,
        "decision": decisions.clip_json(clip, tags),
        "why": {
            "description": best["description"] if best else None,
            "reasons": best["reasons"] if best else [],
        },
        "moments": moments,
        "quality": quality(s, a.id, a.audio_stream_index is not None, bool(sentences)),
        "transcript": {"segments": sentences or 0, "language": language},
        "used_in": _used_in(s, a.id),
        "similar": _similar(s, ids, a.id),
        "burst": _burst(s, ids) if a.kind in ("photo", "live_photo") else None,
    }


def transcript(s: Session, asset_id: int, after: int | None = None) -> dict[str, Any]:
    """The clip's transcript, paged by segment: sentences with their words, each with exact
    times so a click seeks to the word (S11)."""
    a = s.get(Asset, asset_id)
    if a is None:
        raise LookupError(asset_id)
    q = select(TranscriptSegment).where(TranscriptSegment.asset_id == asset_id)
    if after is not None:
        q = q.where(TranscriptSegment.id > after)
    # Written in time order, so id order is time order and a stable key for paging.
    rows = list(s.scalars(q.order_by(TranscriptSegment.id).limit(TRANSCRIPT_PAGE + 1)))
    more = len(rows) > TRANSCRIPT_PAGE
    rows = rows[:TRANSCRIPT_PAGE]
    words: dict[int, list[dict[str, Any]]] = {}
    for w in s.scalars(
        select(TranscriptWord)
        .where(TranscriptWord.segment_id.in_([r.id for r in rows]))
        .order_by(TranscriptWord.start_ticks, TranscriptWord.id)
    ):
        words.setdefault(w.segment_id, []).append(
            {"start": _time(w.start_ticks, a.tb), "end": _time(w.end_ticks, a.tb), "word": w.word}
        )
    return {
        "items": [
            {
                "id": r.id,
                "start": _time(r.start_ticks, a.tb),
                "end": _time(r.end_ticks, a.tb),
                "text": r.text,
                "language": r.language,
                "words": words.get(r.id, []),
            }
            for r in rows
        ],
        "next_after": rows[-1].id if more else None,
    }
