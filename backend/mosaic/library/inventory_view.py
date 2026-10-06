"""S5 Inventory: what the scan found, before analysis (API_MAP; ADR 0038).

Everything comes from the project DB rows L0 wrote. Reasons and fixes are the camera
profiles' catalog texts (``asset.reason`` / ``suggested_fix``, MEDIA_SUPPORT.md), never raw
ffprobe output. Durations are display seconds; dates are the clips' own corrected days.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mosaic.core.time import parse_rational
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    Device,
    DeviceSuggestion,
    MediaFile,
    PhotoGroup,
    SampleFrame,
    Sidecar,
)

KIND = {"iphone": "phone", "gopro": "actioncam", "insta360": "360", "dji": "drone"}
SHOWN = ("video", "photo", "live_photo")


def _camera_key(a: Any) -> str:
    return f"d{a.device_id}" if a.device_id else f"p{a.profile}"


def _seconds(a: Any) -> float:
    return float(a.duration_ticks * parse_rational(a.tb)) if a.duration_ticks and a.tb else 0.0


def _offset_words(ms: int) -> str:
    sign = "ahead" if ms < 0 else "behind"  # the fix moves the clock the other way
    m = abs(ms) // 60_000
    d, rem = divmod(m, 24 * 60)
    h, mins = divmod(rem, 60)
    if d:
        return f"{d} day{'s' if d > 1 else ''} {sign}" if not h else f"{d} d {h} h {sign}"
    return f"{h} h {mins:02d} m {sign}" if h else f"{mins} m {sign}"


def inventory(s: Session) -> dict[str, Any]:
    devices = {d.id: d for d in s.scalars(select(Device))}
    suggestions = {g.device_id: g for g in s.scalars(select(DeviceSuggestion))}
    files_per_asset = dict(
        s.execute(select(AssetFile.asset_id, func.count()).group_by(AssetFile.asset_id)).all()
    )
    first_frame = dict(
        s.execute(
            select(SampleFrame.asset_id, func.min(SampleFrame.id))
            .where(SampleFrame.kept.is_(True))
            .group_by(SampleFrame.asset_id)
        ).all()
    )
    telemetry_assets = set(
        s.scalars(
            select(MediaFile.asset_id)
            .join(Sidecar, Sidecar.owner_media_file_id == MediaFile.id)
            .where(Sidecar.kind == "srt", Sidecar.status == "valid")
        )
    )
    cams: dict[str, dict[str, Any]] = {}
    days: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    footage = 0.0
    clips = photos = limited = 0
    first = last = None
    cols = select(
        Asset.id,
        Asset.kind,
        Asset.device_id,
        Asset.profile,
        Asset.camera_model,
        Asset.duration_ticks,
        Asset.tb,
        Asset.capture_time,
        Asset.color_hint,
        Asset.flags,
    ).where(Asset.kind.in_(SHOWN), Asset.status == "ok")
    for a in s.execute(cols.execution_options(yield_per=1000)):  # streamed (invariant 13)
        key = _camera_key(a)
        dev = devices.get(a.device_id) if a.device_id else None
        c = cams.setdefault(
            key,
            {
                "key": key,
                "label": (dev.label if dev else None) or a.camera_model or a.profile.title(),
                "kind": KIND.get(a.profile, "camera"),
                "clips": 0,
                "photos": 0,
                "files": 0,
                "footage_seconds": 0,
                "badges": set(),
                "sample_id": None,
                "clock": None,
                "device_id": a.device_id,
            },
        )
        if a.kind == "video":
            secs = _seconds(a)
            c["clips"] += 1
            c["footage_seconds"] += secs
            footage += secs
            clips += 1
            if a.capture_time:
                days[a.capture_time[:10]][key] += secs
        else:
            c["photos"] += 1
            photos += 1
            if a.kind == "live_photo":
                c["badges"].add("Live Photo")
            if a.capture_time:
                days[a.capture_time[:10]][key] += 0  # the day exists, with no footage time
        c["files"] += files_per_asset.get(a.id, 1)
        if a.color_hint in ("hlg", "pq"):
            c["badges"].add("HDR")
        elif a.color_hint == "log":
            c["badges"].add("Log")
        if "analysis_only" in (a.flags or []):
            c["badges"].add("360")
            limited += 1
        if a.id in telemetry_assets:
            c["badges"].add("Telemetry")
        if c["sample_id"] is None and a.id in first_frame:
            c["sample_id"] = first_frame[a.id]
        if a.capture_time:
            first = min(first or a.capture_time, a.capture_time)
            last = max(last or a.capture_time, a.capture_time)
    for c in cams.values():
        c["badges"] = sorted(c["badges"])
        c["footage_seconds"] = round(c["footage_seconds"])
        sug = suggestions.get(c["device_id"]) if c["device_id"] else None
        if sug is not None and sug.offset_ms:
            dev = devices[c["device_id"]]
            if sug.offset_ms != dev.clock_offset_ms:
                c["clock"] = {"offset_ms": sug.offset_ms, "words": _offset_words(sug.offset_ms)}
    return {
        "summary": {
            "footage_seconds": round(footage),
            "clips": clips,
            "photos": photos,
            "first_date": first[:10] if first else None,
            "last_date": last[:10] if last else None,
            "cameras": len(cams),
        },
        "cameras": sorted(cams.values(), key=lambda c: (-c["clips"] - c["photos"], c["label"])),
        "days": [
            {"date": d, "by_camera": {k: round(v) for k, v in sorted(by.items())}}
            for d, by in sorted(days.items())
        ],
        "attention": _attention(s, limited),
        "notes": _notes(s),
    }


def _attention(s: Session, limited: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    unsupported = s.execute(
        select(Asset.reason, Asset.suggested_fix, func.count(), func.min(Asset.id))
        .where(Asset.status == "unsupported")
        .group_by(Asset.reason, Asset.suggested_fix)
    )
    for reason, fix, n, _aid in unsupported:
        items.append({"kind": "unreadable", "count": n, "reason": reason, "fix": fix})
    if limited:
        items.append(
            {
                "kind": "limited",
                "count": limited,
                "reason": "MosAic will analyze them but can't edit 360 video yet.",
                "fix": "Export flat versions from Insta360 Studio.",
            }
        )
    offline_n, offline_bytes = s.execute(
        select(func.count(MediaFile.id), func.coalesce(func.sum(MediaFile.size), 0)).where(
            MediaFile.status == "offline"
        )
    ).one()
    if offline_n:
        items.append(
            {
                "kind": "cloud",
                "count": offline_n,
                "bytes": int(offline_bytes),
                "reason": "They're not on this computer yet.",
                "fix": None,
            }
        )
    return items


def _notes(s: Session) -> dict[str, int]:
    chaptered = s.scalar(
        select(func.count()).select_from(
            select(AssetFile.asset_id)
            .group_by(AssetFile.asset_id)
            .having(func.count() > 1)
            .subquery()
        )
    )
    live = s.scalar(select(func.count(Asset.id)).where(Asset.kind == "live_photo"))
    bursts = s.scalar(select(func.count(PhotoGroup.id)).where(PhotoGroup.kind == "burst"))
    return {"chaptered_recordings": chaptered or 0, "live_photos": live or 0, "bursts": bursts or 0}
