"""Project DB (portable, per project) ORM models. Alembic tree: storage/migrations/project.

Time columns hold integers only (ticks with a time-base string, or frames with a rate);
see the float-seconds schema test.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ProjectBase(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class ProjectMeta(ProjectBase):
    __tablename__ = "project_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Provenance(ProjectBase):
    __tablename__ = "provenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    model_version: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    input_keys: Mapped[list[Any]] = mapped_column(JSON, default=list)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String(40))


class Artifact(ProjectBase):
    """Index of artifact blobs. ``location`` is relative to the artifact store root."""

    __tablename__ = "artifact"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    location: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))
    created_at: Mapped[str] = mapped_column(String(40))


# ------------------------------------------------------------------- L0 inventory
# ARCHITECTURE.md §5.2. Raw probe JSON is an artifact blob (``probe_key``); columns hold
# integers only (ADR 0002 G).


class MediaFile(ProjectBase):
    """A physical file under the project root."""

    __tablename__ = "media_file"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rel_path: Mapped[str] = mapped_column(Text, unique=True)
    size: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    fingerprint: Mapped[str] = mapped_column(String(80), index=True)
    media_type: Mapped[str] = mapped_column(String(16))  # video|photo|audio|sidecar|other
    status: Mapped[str] = mapped_column(String(16))
    # pending|ok|unsupported|deferred|offline|missing
    reason: Mapped[str | None] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    probe_key: Mapped[str | None] = mapped_column(String(128))
    container: Mapped[str | None] = mapped_column(String(64))
    profile: Mapped[str | None] = mapped_column(String(32))
    capture_time: Mapped[str | None] = mapped_column(String(40))  # ISO-8601 with offset
    camera_make: Mapped[str | None] = mapped_column(String(64))
    camera_model: Mapped[str | None] = mapped_column(String(128))
    bit_rate: Mapped[int | None] = mapped_column(BigInteger)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("asset.id"), index=True)
    created_at: Mapped[str] = mapped_column(String(40))


class MediaStream(ProjectBase):
    __tablename__ = "media_stream"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"), index=True)
    stream_index: Mapped[int] = mapped_column(Integer)
    codec_type: Mapped[str] = mapped_column(String(16))
    codec_name: Mapped[str | None] = mapped_column(String(32))
    codec_tag: Mapped[str | None] = mapped_column(String(16))
    profile: Mapped[str | None] = mapped_column(String(64))
    time_base: Mapped[str] = mapped_column(String(32))
    start_pts: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ts: Mapped[int | None] = mapped_column(BigInteger)
    nb_frames: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    rate: Mapped[str | None] = mapped_column(String(32))  # r_frame_rate, rational
    avg_rate: Mapped[str | None] = mapped_column(String(32))
    vfr: Mapped[bool] = mapped_column(Boolean, default=False)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    pix_fmt: Mapped[str | None] = mapped_column(String(32))
    bit_depth: Mapped[int | None] = mapped_column(Integer)
    color_range: Mapped[str | None] = mapped_column(String(8))
    color_transfer: Mapped[str | None] = mapped_column(String(32))
    color_primaries: Mapped[str | None] = mapped_column(String(32))
    color_space: Mapped[str | None] = mapped_column(String(32))
    dovi: Mapped[bool] = mapped_column(Boolean, default=False)
    channels: Mapped[int | None] = mapped_column(Integer)
    channel_layout: Mapped[str | None] = mapped_column(String(32))
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    handler: Mapped[str | None] = mapped_column(String(64))


class Asset(ProjectBase):
    """Logical item. A chaptered recording is one Asset over several MediaFiles."""

    __tablename__ = "asset"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # video|photo|live_photo|audio|unsupported
    status: Mapped[str] = mapped_column(String(16))  # ok|unsupported|deferred|missing
    reason: Mapped[str | None] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[str] = mapped_column(String(32))
    group_key: Mapped[str] = mapped_column(String(160), unique=True)
    capture_time: Mapped[str | None] = mapped_column(String(40))
    camera_make: Mapped[str | None] = mapped_column(String(64))
    camera_model: Mapped[str | None] = mapped_column(String(128))
    camera_serial: Mapped[str | None] = mapped_column(String(64))
    color_hint: Mapped[str] = mapped_column(String(16), default="sdr")  # sdr|hlg|pq|log
    tb: Mapped[str | None] = mapped_column(String(32))  # logical time base
    duration_ticks: Mapped[int | None] = mapped_column(BigInteger)
    rate: Mapped[str | None] = mapped_column(String(32))
    vfr: Mapped[bool] = mapped_column(Boolean, default=False)
    hfr: Mapped[bool] = mapped_column(Boolean, default=False)
    display_width: Mapped[int | None] = mapped_column(Integer)
    display_height: Mapped[int | None] = mapped_column(Integer)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    video_stream_index: Mapped[int | None] = mapped_column(Integer)
    audio_stream_index: Mapped[int | None] = mapped_column(Integer)
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class AssetFile(ProjectBase):
    """Logical-time map of an Asset: file ``order`` covers
    ``[logical_start_ticks, logical_start_ticks + duration_ticks)`` in ``asset.tb``."""

    __tablename__ = "asset_file"
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    order: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    logical_start_ticks: Mapped[int] = mapped_column(BigInteger)
    duration_ticks: Mapped[int] = mapped_column(BigInteger)


class Sidecar(ProjectBase):
    __tablename__ = "sidecar"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"), index=True)
    owner_media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id"))
    kind: Mapped[str] = mapped_column(String(16))  # lrf|lrv|thm|srt|xmp|aae
    status: Mapped[str] = mapped_column(String(16))  # valid|invalid|orphan|ignored
    reason: Mapped[str | None] = mapped_column(Text)
    proxy_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


# ------------------------------------------------------------------ L1 analysis
# Times are logical source ticks in the asset's time base (invariants 3 and 4).


class Shot(ProjectBase):
    __tablename__ = "shot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    start_ticks: Mapped[int] = mapped_column(BigInteger)
    end_ticks: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(16))  # adaptive|forced
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class SampleFrame(ProjectBase):
    __tablename__ = "sample_frame"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shot.id"), index=True)
    ticks: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(16))  # scene|interval
    phash: Mapped[str] = mapped_column(String(16))  # 64-bit hex
    kept: Mapped[bool] = mapped_column(Boolean, default=True)
    dup_of: Mapped[int | None] = mapped_column(ForeignKey("sample_frame.id"))
    image_key: Mapped[str | None] = mapped_column(String(128))
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class TechMetric(ProjectBase):
    """A deterministic metric: raw value plus project-normalized percentile (§5.3).

    Attached to a sample (frame metrics) or to a tick range (shake, motion, freeze)."""

    __tablename__ = "tech_metric"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    sample_id: Mapped[int | None] = mapped_column(ForeignKey("sample_frame.id"), index=True)
    start_ticks: Mapped[int] = mapped_column(BigInteger)
    end_ticks: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[float] = mapped_column(Float)
    percentile: Mapped[float | None] = mapped_column(Float)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))
