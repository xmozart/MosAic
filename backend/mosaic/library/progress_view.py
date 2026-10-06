"""S9 Analysis progress: the job's stages in plain words, the live contact sheet, failed
clips and whether the library is ready to browse (API_MAP; ADR 0041).

The pipeline's stages are grouped into the steps the owner sees (VOICE.md words). Notes
are counts read from the project DB; failure reasons are short catalog phrases, never raw
tool output. Durations are display seconds.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from mosaic.core.time import parse_rational
from mosaic.storage.models_control import Job, Task
from mosaic.storage.models_project import (
    Asset,
    MediaFile,
    Mosaic,
    MosaicTile,
    SampleFrame,
    Shot,
    TranscriptSegment,
    VisualObservation,
)

# (key, words, pipeline stages). A stage may feed several steps (``visual`` finds shots,
# picks frames and measures quality in one task); unknown stages fall into the last step.
GROUPS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("look", "Looking through your footage", frozenset({"scan", "probe", "group", "benchmark"})),
    ("previews", "Making previews", frozenset({"proxy", "waveform"})),
    ("shots", "Finding shots", frozenset({"visual"})),
    ("frames", "Picking frames", frozenset({"visual", "photo"})),
    ("speech", "Listening", frozenset({"audio"})),
    ("quality", "Measuring quality", frozenset({"visual", "telemetry", "photo", "normalize"})),
    (
        "scenes",
        "Understanding scenes",
        frozenset({"embed", "segments", "photo_segment", "mosaics", "vision", "deepen", "review"}),
    ),
    ("similar", "Grouping similar shots", frozenset({"similarity"})),
    ("library", "Building your library", frozenset()),
)
KNOWN = frozenset().union(*(g[2] for g in GROUPS))
L0 = frozenset({"scan", "probe", "group", "benchmark"})
DONE = frozenset({"done", "skipped"})
FAILED = frozenset({"failed"})
RUNNING = frozenset({"running", "leased"})
FAILURES_SHOWN = 50


def stage_levels() -> dict[str, int]:
    """Analysis level of each per-asset stage (ANALYSIS_MODES §1)."""
    from mosaic.jobs.registry import load_handlers
    from mosaic.media import inventory

    load_handlers()  # every stage module registers itself
    return {st.name: st.level for st in inventory.ASSET_STAGES}


def stage_status_counts(control: Session, job_id: int) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for stage, status, n in control.execute(
        select(Task.stage, Task.status, func.count())
        .where(Task.job_id == job_id)
        .group_by(Task.stage, Task.status)
    ):
        out[stage][status] += n
    return out


def ready_to_browse(counts: dict[str, dict[str, int]], levels: dict[str, int]) -> bool:
    """L0 and every per-asset L1 task are finished (API_MAP ``analysis.ready_to_browse``).
    Project-wide stages run after the per-asset L2 work, so they are not waited for."""
    per_asset_l1 = [st for st in counts if st not in L0 and levels.get(st, 99) <= 1]
    if not per_asset_l1:
        return False  # the scan has not spawned the per-asset work yet
    finished = all(
        sum(n for status, n in counts[st].items() if status not in DONE | FAILED) == 0
        for st in [*per_asset_l1, *(st for st in counts if st in L0)]
    )
    # Something must have worked: a run where every clip failed has nothing to browse.
    return finished and any(counts[st].get(x, 0) for st in per_asset_l1 for x in DONE)


def _duration(seconds: float) -> str:
    s = round(seconds)
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d} m" if h else f"{m} m"


def _notes(s: Session) -> dict[str, str]:
    videos = s.scalar(select(func.count(Asset.id)).where(Asset.kind == "video")) or 0
    photos = (
        s.scalar(select(func.count(Asset.id)).where(Asset.kind.in_(("photo", "live_photo")))) or 0
    )
    shots = s.scalar(select(func.count(Shot.id))) or 0
    frames = s.scalar(select(func.count(SampleFrame.id))) or 0
    kept = s.scalar(select(func.count(SampleFrame.id)).where(SampleFrame.kept.is_(True))) or 0
    speech = 0.0
    for ticks, tb in s.execute(
        select(func.sum(TranscriptSegment.end_ticks - TranscriptSegment.start_ticks), Asset.tb)
        .join(Asset, Asset.id == TranscriptSegment.asset_id)
        .group_by(Asset.tb)
    ):
        if ticks and tb:
            speech += float(ticks * parse_rational(tb))  # display only
    sheets = s.scalar(select(func.count(Mosaic.id))) or 0
    seen = s.scalar(select(func.count(func.distinct(VisualObservation.mosaic_id)))) or 0
    out = {"look": f"{videos:,} clips · {photos:,} photos"}
    if shots:
        out["shots"] = f"{shots:,} shots"
    if frames:
        out["frames"] = f"{frames:,} frames → {kept:,} kept"
    if speech:
        out["speech"] = f"{_duration(speech)} of speech"
    if sheets:
        out["scenes"] = f"sheet {seen:,} of {sheets:,}"
    return out


def _file_name(s: Session, asset_id: int) -> str | None:
    rel = s.scalar(
        select(MediaFile.rel_path)
        .where(MediaFile.asset_id == asset_id)
        .order_by(MediaFile.id)
        .limit(1)
    )
    return rel.rsplit("/", 1)[-1] if rel else None


def _trip_day(s: Session, capture_time: str | None) -> int | None:
    if not capture_time:
        return None
    first = s.scalar(select(func.min(Asset.capture_time)).where(Asset.capture_time.is_not(None)))
    if not first:
        return None
    return (date.fromisoformat(capture_time[:10]) - date.fromisoformat(first[:10])).days + 1


def _live(s: Session) -> dict[str, Any] | None:
    """The latest contact sheet the vision model described, with one of its descriptions."""
    obs = s.scalar(select(VisualObservation).order_by(VisualObservation.id.desc()).limit(1))
    if obs is None:
        return None
    sheet = s.get(Mosaic, obs.mosaic_id)
    if sheet is None:
        return None
    asset = s.get(Asset, sheet.asset_id)
    tiles = s.scalar(select(func.count()).where(MosaicTile.mosaic_id == sheet.id)) or 0
    text = obs.data.get("description") if isinstance(obs.data, dict) else None
    return {
        "mosaic_id": sheet.id,
        "tiles": tiles,
        "cols": sheet.cols,
        "rows": sheet.rows,
        "description": text,
        "file": _file_name(s, sheet.asset_id),
        "day": _trip_day(s, asset.capture_time if asset else None),
    }


_TIMEOUT = re.compile(r"time(d)?\s*out|timeout", re.IGNORECASE)


def _reason(error: str | None) -> str:
    """A short phrase for a failed clip (VOICE.md); raw tool output is never shown."""
    if error and _TIMEOUT.search(error):
        return "timed out"
    if error and ("PermanentError" in error or "decode" in error.lower()):
        return "couldn't be read"
    return "couldn't be processed"


def _failures(control: Session, s: Session, job_id: int) -> dict[str, Any]:
    """Failed clips of the job: counted and paged in SQL, file names for the shown page
    only (invariant 13)."""
    aid = func.json_extract(Task.params, "$.asset_id")
    failed = (
        select(aid.label("aid"), func.min(Task.id).label("tid"))
        .where(Task.job_id == job_id, Task.status == "failed")
        .group_by(aid)
        .subquery()
    )
    count = control.scalar(select(func.count()).select_from(failed)) or 0
    page = list(
        control.execute(
            select(failed.c.aid, Task.stage, Task.error)
            .join(Task, Task.id == failed.c.tid)
            .order_by(failed.c.tid)
            .limit(FAILURES_SHOWN)
        )
    )
    ids = [r.aid for r in page if isinstance(r.aid, int)]
    names: dict[int, str] = {}
    for asset_id, rel in s.execute(
        select(MediaFile.asset_id, MediaFile.rel_path)
        .where(MediaFile.asset_id.in_(ids))
        .order_by(MediaFile.id.desc())
    ):
        if asset_id is not None:  # descending ids: the asset's first file wins
            names[asset_id] = rel.rsplit("/", 1)[-1]
    items = [
        {
            "asset_id": r.aid,
            "file": names.get(r.aid) if isinstance(r.aid, int) else None,
            "stage": r.stage,
            "reason": _reason(r.error),
        }
        for r in page
    ]
    return {"count": count, "items": items}


def step_state(done: int, failed: int, running: int, total: int, status: str) -> str:
    """One step's state. A cancelled job keeps its work: unfinished steps are pending
    (S9 "Cancelled (work kept, Resume)"); only a failed job marks them failed."""
    if total and done + failed == total:
        return "done"
    if status.startswith("paused"):
        return "paused"
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "pending"
    return "running" if (running or done or failed) else "pending"


def analysis_progress(control: Session, s: Session, job: Job) -> dict[str, Any]:
    counts = stage_status_counts(control, job.id)
    levels = stage_levels()
    notes = _notes(s)
    steps = []
    for key, words, stages in GROUPS:
        members = [st for st in counts if (st in stages) or (key == "library" and st not in KNOWN)]
        if not members:
            continue
        total = sum(sum(counts[st].values()) for st in members)
        done = sum(counts[st].get(x, 0) for st in members for x in DONE)
        failed = sum(counts[st].get(x, 0) for st in members for x in FAILED)
        running = sum(counts[st].get(x, 0) for st in members for x in RUNNING)
        state = step_state(done, failed, running, total, job.status)
        note = notes.get(key)
        if key == "previews" or (note is None and state != "pending"):
            note = f"{done:,} of {total:,}"
        steps.append(
            {
                "key": key,
                "label": words,
                "state": state,
                "done": done,
                "failed": failed,
                "total": total,
                "pct": 100 * (done + failed) // total if total else 0,
                "note": note if state != "pending" else None,
            }
        )
    return {
        "job_id": job.id,
        "kind": job.kind,
        "mode": (job.params or {}).get("preset") or (job.params or {}).get("mode"),
        "steps": steps,
        "ready_to_browse": job.kind == "analysis" and ready_to_browse(counts, levels),
        "live": _live(s),
        "failures": _failures(control, s, job.id),
        "clips": _clips(s, counts, levels, control, job.id),
    }


def _clips(
    s: Session,
    counts: dict[str, dict[str, int]],
    levels: dict[str, int],
    control: Session,
    job_id: int,
) -> dict[str, int]:
    """Video clips in this job and how many have every per-asset task finished ("173 of
    412 clips fully analyzed"), aggregated in SQL. Photos have per-asset tasks too; an
    asset counts as a clip when it has a task of a video-only stage."""
    from mosaic.media import inventory

    per_asset = [st for st in counts if st in levels]
    video_only = {st.name for st in inventory.ASSET_STAGES if st.kinds == ("video",)}
    if not per_asset or not video_only & set(per_asset):
        videos = s.scalar(select(func.count(Asset.id)).where(Asset.kind == "video")) or 0
        return {"done": 0, "total": videos}
    aid = func.json_extract(Task.params, "$.asset_id")
    unfinished = case((Task.status.in_(tuple(DONE | FAILED)), 0), else_=1)
    per = (
        select(
            aid.label("aid"),
            func.sum(unfinished).label("open"),
            func.max(case((Task.stage.in_(tuple(video_only)), 1), else_=0)).label("video"),
        )
        .where(Task.job_id == job_id, Task.stage.in_(per_asset))
        .group_by(aid)
        .subquery()
    )
    total = control.scalar(select(func.count()).select_from(per).where(per.c.video == 1)) or 0
    done = (
        control.scalar(
            select(func.count()).select_from(per).where(per.c.video == 1, per.c.open == 0)
        )
        or 0
    )
    return {"done": done, "total": total}
