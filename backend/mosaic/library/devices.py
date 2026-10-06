"""Devices and clock correction (MEDIA_SUPPORT.md §4, ADR 0027).

- **Devices.** Each asset belongs to a device, keyed by make, model and serial when the
  file states them, else by its camera profile.
- **Corrected time.** A device's clock offset (integer milliseconds) is added to the raw
  capture time of each of its assets. `Asset.capture_time` holds the corrected time,
  which every ordering and day grouping reads. Changing an offset rewrites only those
  strings: no analysis is redone.
- **Suggestions** come from evidence pairs: a clip or photo of the device that looks like
  the same moment as one from the reference device (a phone, whose clock follows network
  time, when the project has one). The densest cluster of time differences is the
  suggested offset. The owner accepts or edits it (CLI now, the S6 screen in M2); nothing
  is applied on its own.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from fractions import Fraction
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from mosaic.ai.registry import task_embedder
from mosaic.core.keys import artifact_key
from mosaic.core.time import parse_rational
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.registry import task
from mosaic.library import moments as _moments  # noqa: F401 - registers "moments" first
from mosaic.media import inventory
from mosaic.storage import provenance, sqlite_vec_index
from mosaic.storage.models_project import (
    Asset,
    Device,
    DeviceSuggestion,
    Embedding,
    Segment,
)

CLOCK_VERSION = "clock/1"
SAMPLES_PER_DEVICE = 200  # segments of a device compared with the reference
NEIGHBOURS = 64  # deep enough to get past the device's own look-alike segments
MATCH_MAX_DISTANCE = 0.12  # cosine distance for "the same moment"
MAX_OFFSET = timedelta(hours=48)  # clocks further off than this are not suggested
CLUSTER = timedelta(minutes=2)  # candidate offsets this close agree
MIN_PAIRS = 3  # evidence pairs needed for a suggestion
CONSISTENT = timedelta(seconds=60)  # a smaller offset is "consistent", not suggested


def device_identity(
    make: str | None, model: str | None, serial: str | None, profile: str
) -> tuple[str, str]:
    """(key, label) of the device an asset came from."""
    if make or model or serial:
        key = f"{make or ''}|{model or ''}|{serial or ''}"
        label = " ".join(x for x in (make, model) if x) or (serial or profile)
    else:
        key = f"profile:{profile}"
        label = {"generic": "Unknown camera"}.get(profile, profile.replace("_", " ").title())
    return key, label


def ensure_device(
    s: Session, make: str | None, model: str | None, serial: str | None, profile: str
) -> Device:
    key, label = device_identity(make, model, serial, profile)
    dev = s.scalar(select(Device).where(Device.key == key))
    if dev is None:
        dev = Device(
            key=key,
            make=make,
            model=model,
            serial=serial,
            label=label,
            clock_offset_ms=0,
            offset_source="none",
        )
        s.add(dev)
        s.flush()
    return dev


def shift(raw: str | None, offset_ms: int, utc_offset_min: int | None = None) -> str | None:
    """``raw`` (ISO 8601) moved by ``offset_ms``. An offset-aware time is shown in
    ``utc_offset_min`` when given (the reference device's zone), else keeps its own
    offset; a camera-local (naive) time stays naive."""
    if raw is None or (offset_ms == 0 and utc_offset_min is None):
        return raw
    try:
        t = datetime.fromisoformat(raw) + timedelta(milliseconds=offset_ms)
    except ValueError:
        return raw
    if t.tzinfo is not None and utc_offset_min is not None:
        t = t.astimezone(timezone(timedelta(minutes=utc_offset_min)))
    return t.isoformat(timespec="milliseconds" if t.microsecond else "seconds")


class _Keep(Enum):
    ZONE = 0  # set_offset: leave the device's adopted zone as it is


KEEP_ZONE = _Keep.ZONE


def set_offset(
    s: Session,
    device_id: int,
    offset_ms: int,
    source: str,
    utc_offset_min: int | _Keep | None = KEEP_ZONE,
) -> int:
    """Set a device's clock offset and rewrite its assets' corrected times. Accepting a
    suggestion also sets the zone (the reference's); a hand adjustment keeps the zone
    already adopted. Returns the number of assets updated."""
    dev = s.get(Device, device_id)
    if dev is None:
        raise LookupError(f"no device {device_id}")
    dev.clock_offset_ms, dev.offset_source = int(offset_ms), source
    if not isinstance(utc_offset_min, _Keep):
        dev.utc_offset_min = utc_offset_min
    zone = dev.utc_offset_min
    rows = s.execute(
        select(Asset.id, Asset.capture_time_raw).where(Asset.device_id == device_id)
    ).all()
    for aid, raw in rows:
        s.execute(
            update(Asset).where(Asset.id == aid).values(capture_time=shift(raw, offset_ms, zone))
        )
    return len(rows)


# --------------------------------------------------------------- suggestion


@dataclass(frozen=True)
class Evidence:
    device_segment: int
    reference_segment: int
    device_time: str
    reference_time: str
    distance: float
    offset_ms: int


def densest(offsets: list[int], width_ms: int) -> list[int]:
    """The largest group of offsets within ``width_ms`` of each other (sorted window)."""
    xs = sorted(offsets)
    best: list[int] = []
    lo = 0
    for hi in range(len(xs)):
        while xs[hi] - xs[lo] > width_ms:
            lo += 1
        if hi - lo + 1 > len(best):
            best = xs[lo : hi + 1]
    return best


def _segment_times(
    s: Session, device_id: int, corrected: bool = False
) -> list[tuple[int, datetime, str, str]]:
    """(segment id, midpoint time, owner kind, ISO) for a device's segments: from the raw
    capture time, or the corrected one (the reference device's own fix counts)."""
    out = []
    for a in s.scalars(select(Asset).where(Asset.device_id == device_id, Asset.status == "ok")):
        iso = a.capture_time if corrected else a.capture_time_raw
        if not iso or not a.tb:
            continue
        try:
            start = datetime.fromisoformat(iso)
        except ValueError:
            continue
        tb = parse_rational(a.tb)
        kind = "segment" if a.kind == "video" else "photo_segment"
        for sid, s0, s1 in s.execute(
            select(Segment.id, Segment.start_ticks, Segment.end_ticks).where(
                Segment.asset_id == a.id
            )
        ):
            mid = start + timedelta(seconds=float(Fraction(s0 + s1, 2) * tb))
            out.append((sid, mid, kind, mid.isoformat(timespec="seconds")))
    return out


def _reference(s: Session) -> Device | None:
    """The device whose clock is trusted: a phone (network time) if present, else the
    device with the most assets."""
    sizes = dict(
        s.execute(
            select(Asset.device_id, func.count(Asset.id))
            .where(Asset.device_id.is_not(None))
            .group_by(Asset.device_id)
        ).all()
    )
    devices = [d for d in s.scalars(select(Device)) if sizes.get(d.id)]
    phones = [d for d in devices if (d.make or "").lower() == "apple"]
    pool = phones or devices
    return max(pool, key=lambda d: (sizes[d.id], -d.id), default=None)


@dataclass(frozen=True)
class Suggestion:
    device_id: int
    reference_id: int
    offset_ms: int  # the absolute offset to set on the device
    utc_offset_min: int | None  # the reference's usual zone, for day boundaries
    pairs: int  # evidence pairs that agree
    evidence: list[Evidence]


def suggest(s: Session, model: str, dim: int) -> list[Suggestion]:
    """A suggestion for every device whose clock can be matched to the reference's."""
    ref = _reference(s)
    if ref is None:
        return []
    ref_items = _segment_times(s, ref.id, corrected=True)
    ref_times = {sid: (t, iso) for sid, t, _, iso in ref_items}
    if not ref_times:
        return []
    zones = Counter(
        int(t.utcoffset().total_seconds() // 60)  # type: ignore[union-attr]
        for _, t, _, _ in ref_items
        if t.tzinfo is not None
    )
    ref_zone = zones.most_common(1)[0][0] if zones else None
    out = []
    for dev in s.scalars(select(Device).where(Device.id != ref.id)):
        items = _segment_times(s, dev.id)
        if not items:
            continue
        items.sort(key=lambda it: it[0])
        step = max(1, len(items) // SAMPLES_PER_DEVICE)
        evidence: list[Evidence] = []
        for sid, t, kind, iso in items[::step]:
            vec = _vector(s, kind, sid, model)
            if vec is None:
                continue
            for other_kind in ("segment", "photo_segment"):
                index = sqlite_vec_index.index_name(model, dim, other_kind)
                if not _exists(s, index):
                    continue
                for emb_id, dist in sqlite_vec_index.knn(s, index, vec, NEIGHBOURS):
                    if dist > MATCH_MAX_DISTANCE:
                        break  # hits come nearest first
                    owner = s.scalar(select(Embedding.owner_id).where(Embedding.id == emb_id))
                    if owner is None or owner not in ref_times:
                        continue  # the device's own segments, or another device's
                    rt, riso = ref_times[owner]
                    if (rt.tzinfo is None) != (t.tzinfo is None):
                        continue  # camera-local vs offset-aware: not comparable
                    delta = rt - t
                    if abs(delta) > MAX_OFFSET:
                        continue
                    evidence.append(Evidence(sid, owner, iso, riso, float(dist), _ms(delta)))
        if not evidence:
            continue
        cluster = densest([e.offset_ms for e in evidence], _ms(CLUSTER))
        if len(cluster) < MIN_PAIRS:
            continue
        offset = int(statistics.median(cluster))
        agreeing = [e for e in evidence if abs(e.offset_ms - offset) <= _ms(CLUSTER)]
        best = sorted(agreeing, key=lambda e: e.distance)[:3]
        aware = sum(1 for it in items if it[1].tzinfo) * 2 > len(items)  # the majority
        out.append(
            Suggestion(dev.id, ref.id, offset, ref_zone if aware else None, len(agreeing), best)
        )
    return out


def _ms(d: timedelta) -> int:
    return d.days * 86_400_000 + d.seconds * 1000 + d.microseconds // 1000


def _vector(s: Session, kind: str, owner: int, model: str) -> np.ndarray | None:
    blob = s.scalar(
        select(Embedding.vector).where(
            Embedding.owner_kind == kind, Embedding.owner_id == owner, Embedding.model == model
        )
    )
    return np.frombuffer(blob, dtype=np.float32) if blob is not None else None


def _exists(s: Session, table: str) -> bool:
    return (
        s.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :n"), {"n": table}
        ).first()
        is not None
    )


def is_consistent(offset_ms: int) -> bool:
    return abs(offset_ms) < _ms(CONSISTENT)


def _key(ctx: TaskContext) -> str:
    h = hashlib.sha256()
    model = task_embedder(ctx).model
    with ctx.project.db.session() as s:
        for row in s.execute(
            select(
                Asset.id, Asset.device_id, Asset.capture_time_raw, Asset.capture_time, Asset.status
            ).order_by(Asset.id)
        ):
            h.update(repr(tuple(row)).encode())
        for emb in s.execute(
            select(Embedding.owner_kind, Embedding.owner_id, Embedding.provenance_id)
            .where(
                Embedding.owner_kind.in_(("segment", "photo_segment")),
                Embedding.model == model,
            )
            .order_by(Embedding.owner_kind, Embedding.owner_id)
        ):
            h.update(repr(tuple(emb)).encode())
    return artifact_key(
        "clock",
        project_id=ctx.project.id,
        inputs=h.hexdigest(),
        config={
            "model": model,
            "samples": SAMPLES_PER_DEVICE,
            "max_distance": MATCH_MAX_DISTANCE,
            "cluster_ms": _ms(CLUSTER),
            "min_pairs": MIN_PAIRS,
        },
        version=CLOCK_VERSION,
    )


def _is_done(ctx: TaskContext) -> bool:
    return ctx.project.artifacts.exists("clock", _key(ctx))


@task("library.clock", is_done=_is_done)
def clock_task(ctx: TaskContext) -> dict[str, Any]:
    """Suggest clock offsets (never applies them)."""
    key = _key(ctx)
    emb = task_embedder(ctx)
    with ctx.project.db.session() as s:
        found = suggest(s, emb.model, emb.dim)
    with ctx.write() as s:
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="clock", algorithm_version=CLOCK_VERSION, model=emb.model, input_keys=[key]
            ),
        )
        s.execute(delete(DeviceSuggestion))
        for sg in found:
            s.add(
                DeviceSuggestion(
                    device_id=sg.device_id,
                    reference_device_id=sg.reference_id,
                    offset_ms=sg.offset_ms,
                    utc_offset_min=sg.utc_offset_min,
                    pairs=sg.pairs,
                    evidence=[e.__dict__ for e in sg.evidence],
                    provenance_id=prov,
                )
            )
    result = {
        "suggested": sum(1 for sg in found if not is_consistent(sg.offset_ms)),
        "consistent": sum(1 for sg in found if is_consistent(sg.offset_ms)),
    }
    ctx.project.artifacts.put_json("clock", key, result, provenance_id=prov)
    return result


def submit_time_refresh(executor: Any, principal: Any, project: Any) -> int:
    """After an offset change: rebuild what orders or groups by time (captures, clock
    suggestions, summaries). No analysis is redone."""
    from mosaic.library.summaries import summaries_spec
    from mosaic.media.pipeline import job_cost_limit

    tasks = [
        TaskSpec(
            kind="library.moments",
            stage="moments",
            resource_class=ResourceClass.CPU,
            label="moments",
        ),
        # Suggestions read the reference's corrected times: refresh them too.
        TaskSpec(
            kind="library.clock",
            stage="clock",
            resource_class=ResourceClass.CPU,
            label="clock",
            deps=[0],
        ),
        summaries_spec(deps=[1]),
    ]
    return int(
        executor.submit(
            principal,
            JobSpec(
                project_id=project.id,
                kind="time-refresh",
                cost_limit_usd=job_cost_limit(principal),
                tasks=tasks,
            ),
        )
    )


CLOCK_STAGE = inventory.StageDef("clock", "library.clock", ResourceClass.CPU, after=("moments",))
inventory.PROJECT_STAGES.append(CLOCK_STAGE)


def parse_offset(text: str) -> int:
    """An offset in milliseconds from ``+5h``, ``-1h30m``, ``+90s``, ``-00:30:00`` or
    ``+1500ms``."""
    t = text.strip().replace(" ", "")
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-")
    if m := re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", t):
        h, mnt, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return sign * ((h * 3600 + mnt * 60 + sec) * 1000)
    parts = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+)s)?(?:(\d+)ms)?", t)
    if not t or parts is None or not any(parts.groups()):
        raise ValueError(f"not an offset: {text!r} (examples: +5h, -1h30m, +90s, -00:30:00)")
    h, mnt, sec, ms = (int(x or 0) for x in parts.groups())
    return sign * ((h * 3600 + mnt * 60 + sec) * 1000 + ms)


def describe(offset_ms: int) -> str:
    """ "5 h 00 m ahead" / "12 min behind" / "on time" for an offset to add."""
    if is_consistent(offset_ms):
        return "on time"
    # A positive correction means the device's clock is behind.
    word = "behind" if offset_ms > 0 else "ahead"
    total = abs(offset_ms) // 1000
    h, rem = divmod(total, 3600)
    m = rem // 60
    return (f"{h} h {m:02d} m" if h else f"{m} min") + f" {word}"


def device_rows(s: Session) -> list[dict[str, Any]]:
    counts = dict(
        s.execute(select(Asset.device_id, func.count(Asset.id)).group_by(Asset.device_id)).all()
    )
    sugg = {r.device_id: r for r in s.scalars(select(DeviceSuggestion))}
    out = []
    for d in s.scalars(select(Device).order_by(Device.id)):
        sg = sugg.get(d.id)
        suggestion = None
        if sg is not None:
            # What is still off after the offset already set on the device.
            residual = sg.offset_ms - d.clock_offset_ms
            suggestion = {
                "offset_ms": sg.offset_ms,
                "utc_offset_min": sg.utc_offset_min,
                "verdict": describe(residual),
                "applied": is_consistent(residual),
                "reference_device_id": sg.reference_device_id,
                "pairs": sg.pairs,
                "evidence": sg.evidence,
            }
        out.append(
            {
                "id": d.id,
                "label": d.label,
                "make": d.make,
                "model": d.model,
                "serial": d.serial,
                "assets": counts.get(d.id, 0),
                "clock_offset_ms": d.clock_offset_ms,
                "offset_source": d.offset_source,
                "utc_offset_min": d.utc_offset_min,
                "lut_path": d.lut_path,
                "suggestion": suggestion,
            }
        )
    return out


def format_offset(offset_ms: int) -> str:
    """``+5:00:00`` style, for display."""
    sign = "-" if offset_ms < 0 else "+"
    total = abs(offset_ms) // 1000
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{sign}{h}:{m:02d}:{sec:02d}"


def set_lut(project: Any, device_id: int, path: str | None) -> str | None:
    """Assign (or with ``None`` remove) a device's LUT: copied once to a private temp file,
    validated and hashed there, stored in the artifact store by content, then recorded on
    the device. Returns the artifact key. Proxies and renders of the device change, so
    the owner re-runs the analysis to apply it."""
    import shutil
    import stat
    import tempfile
    from pathlib import Path

    from mosaic.media import lut

    with project.db.session() as s:
        if s.get(Device, device_id) is None:
            raise LookupError(f"no device {device_id}")
    key = None
    src = Path(path).expanduser().resolve() if path is not None else None
    if src is not None:
        if src.suffix.lower() != ".cube":
            raise lut.LutError("a LUT must be a .cube file")
        try:
            st = src.stat()
        except OSError as exc:
            raise lut.LutError(f"cannot read the LUT: {exc.strerror or exc}") from None
        if not stat.S_ISREG(st.st_mode):
            raise lut.LutError("the LUT is not a regular file")
        if st.st_size > lut.MAX_BYTES:
            raise lut.LutError("the LUT file is too large")
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "lut.cube"
            shutil.copyfile(src, copy)  # one read of the owner's file
            lut.check_cube(copy)
            key = lut.lut_key(lut.digest(copy))
            if not project.artifacts.exists("lut", key):
                with project.write() as s:
                    prov = provenance.record(
                        s, provenance.ProvenanceInfo(kind="lut", input_keys=[key])
                    )
                project.artifacts.put_file("lut", key, copy, provenance_id=prov)
    with project.write() as s:
        dev = s.get(Device, device_id)
        assert dev is not None
        dev.lut_path = str(src) if src is not None else None
        dev.lut_key = key
    return key


def asset_lut(s: Session, asset: Asset) -> str | None:
    """The artifact key of the LUT for an asset's device, if any."""
    if asset.device_id is None:
        return None
    return s.scalar(select(Device.lut_key).where(Device.id == asset.device_id))
