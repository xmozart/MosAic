"""Project DB (portable, per project) ORM models. Alembic tree: storage/migrations/project.

Time columns hold integers only (ticks with a time-base string, or frames with a rate);
see the float-seconds schema test.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
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
    method: Mapped[str] = mapped_column(String(16))  # adaptive|threshold|forced
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
    dup_reason: Mapped[str | None] = mapped_column(String(16))  # phash|embedding
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


# ------------------------------------------------------------------------ audio
# Whisper's float seconds are converted to ticks at the module boundary (ADR 0002 G).


class AudioEvent(ProjectBase):
    """A detected audio span: ``speech`` (VAD) for now; music, applause etc. later."""

    __tablename__ = "audio_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    start_ticks: Mapped[int] = mapped_column(BigInteger)
    end_ticks: Mapped[int] = mapped_column(BigInteger)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class TranscriptSegment(ProjectBase):
    __tablename__ = "transcript_segment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    start_ticks: Mapped[int] = mapped_column(BigInteger)
    end_ticks: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(8))
    avg_logprob: Mapped[float | None] = mapped_column(Float)
    no_speech_prob: Mapped[float | None] = mapped_column(Float)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class TranscriptWord(ProjectBase):
    """A word with its source ticks. Provenance comes through its segment."""

    __tablename__ = "transcript_word"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("transcript_segment.id"), index=True)
    start_ticks: Mapped[int] = mapped_column(BigInteger)
    end_ticks: Mapped[int] = mapped_column(BigInteger)
    word: Mapped[str] = mapped_column(Text)
    probability: Mapped[float | None] = mapped_column(Float)


# ------------------------------------------------------- embeddings and segments


class Embedding(ProjectBase):
    """An L2-normalized float32 vector for a sample or a segment, per model.

    Vectors are mirrored into a sqlite-vec index named after the model and dimension
    (ARCHITECTURE.md §12); a model change creates a new index."""

    __tablename__ = "embedding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(String(16))  # sample|segment|photo_segment
    owner_id: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(128))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))

    __table_args__ = (Index("ix_embedding_owner", "owner_kind", "owner_id", "model"),)


class SimilarityGroup(ProjectBase):
    __tablename__ = "similarity_group"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    method: Mapped[str] = mapped_column(String(32))  # embedding
    size: Mapped[int] = mapped_column(Integer)
    best_segment_id: Mapped[int | None] = mapped_column(Integer)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class Segment(ProjectBase):
    """Editorially coherent sub-range of a shot (1–20 s); the unit of AI analysis and
    selection (ARCHITECTURE.md §5.3)."""

    __tablename__ = "segment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shot.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    start_ticks: Mapped[int] = mapped_column(BigInteger)
    end_ticks: Mapped[int] = mapped_column(BigInteger)
    usable_start_ticks: Mapped[int] = mapped_column(BigInteger)
    usable_end_ticks: Mapped[int] = mapped_column(BigInteger)
    has_speech: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[float | None] = mapped_column(Float)  # higher is better; for "best of"
    similarity_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("similarity_group.id"), index=True
    )
    group_best: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


# ------------------------------------------------------------ L2 vision and decisions


class Mosaic(ProjectBase):
    """A labelled contact sheet sent to the vision model (ARCHITECTURE.md §8 stage 10)."""

    __tablename__ = "mosaic"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    image_key: Mapped[str] = mapped_column(String(128))
    cols: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    tile_width: Mapped[int] = mapped_column(Integer)
    tile_height: Mapped[int] = mapped_column(Integer)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class MosaicTile(ProjectBase):
    """Tile ``T07`` ↔ sample: the model cites tiles, code resolves them to source ticks."""

    __tablename__ = "mosaic_tile"
    mosaic_id: Mapped[int] = mapped_column(ForeignKey("mosaic.id"), primary_key=True)
    tile: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1-based: T01
    sample_id: Mapped[int] = mapped_column(ForeignKey("sample_frame.id"))
    segment_id: Mapped[int] = mapped_column(ForeignKey("segment.id"), index=True)
    ticks: Mapped[int] = mapped_column(BigInteger)


class VisualObservation(ProjectBase):
    """The structured vision observation of one segment (ARCHITECTURE.md §5.3 ``visual``)."""

    __tablename__ = "visual_observation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segment.id"), unique=True)
    mosaic_id: Mapped[int] = mapped_column(ForeignKey("mosaic.id"))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class Disposition(ProjectBase):
    """USE/MAYBE/REJECT for a segment, with reasons. ``source`` user rows are hard
    constraints that analysis never overwrites (invariant 10).

    Rows are anchored to the source range they were made on (``anchor_*``, asset ticks):
    when segments are rebuilt, user rows are detached (``segment_id`` NULL) instead of
    deleted and re-attached to the new segment they overlap most (ADR 0013)."""

    __tablename__ = "disposition"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segment.id"), index=True)
    anchor_start_ticks: Mapped[int] = mapped_column(BigInteger)
    anchor_end_ticks: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(8))  # ai|user
    status: Mapped[str] = mapped_column(String(8))  # USE|MAYBE|REJECT
    reasons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    roles: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provenance_id: Mapped[int | None] = mapped_column(ForeignKey("provenance.id"))
    updated_at: Mapped[str] = mapped_column(String(40))

    __table_args__ = (Index("ux_disposition_segment_source", "segment_id", "source", unique=True),)


# ------------------------------------------------------------------------ editing


class Edit(ProjectBase):
    """A named edit: a request and its immutable versions (ARCHITECTURE.md §13)."""

    __tablename__ = "edit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(26), unique=True)  # ULID: the API's edit id
    name: Mapped[str] = mapped_column(String(120))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class EditVersion(ProjectBase):
    """An immutable edit snapshot. ``timeline`` holds integer-frame events with integer
    source ticks (invariant 3); the JSON export is derived from this row (invariant 7)."""

    __tablename__ = "edit_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edit_id: Mapped[int] = mapped_column(ForeignKey("edit.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    creator: Mapped[str] = mapped_column(String(8))  # user|ai|system (ARCHITECTURE.md §13)
    reason: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(128), index=True)  # inputs + config + versions
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    rate: Mapped[str] = mapped_column(String(32))
    beats: Mapped[list[Any]] = mapped_column(JSON)
    timeline: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    findings: Mapped[list[Any]] = mapped_column(JSON)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))
    created_at: Mapped[str] = mapped_column(String(40))

    __table_args__ = (Index("ux_edit_version", "edit_id", "version", unique=True),)


class Render(ProjectBase):
    """A preview or final render of one edit version (ARCHITECTURE.md §10). The output file
    lives under the workspace's ``renders/``; chunks are cached artifacts."""

    __tablename__ = "render"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edit_id: Mapped[int] = mapped_column(ForeignKey("edit.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12))  # pending|done|failed
    job_id: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str | None] = mapped_column(Text)  # relative to the workspace
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))


class TripContextRow(ProjectBase):
    """The project's confirmed trip context (one row, id 1; PRODUCT.md §3)."""

    __tablename__ = "trip_context"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(12))  # user|ai_parsed
    updated_at: Mapped[str] = mapped_column(String(40))


class DeepReview(ProjectBase):
    """L3 observation of one segment from full-resolution frames (ANALYSIS_MODES.md §1).
    Same vocabulary as ``visual_observation``; takes precedence over it when present."""

    __tablename__ = "deep_review"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segment.id"), unique=True)
    key: Mapped[str] = mapped_column(String(128))  # everything the review depends on
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    context_digest: Mapped[str] = mapped_column(String(16))
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class AssetStage(ProjectBase):
    """The artifact key that produced an asset's current rows of a stage (``visual``,
    ``audio``). Those rows are replaced on each run, so an existing artifact alone does
    not prove they are current once modes can switch back (ADR 0020). An empty key means
    a run started and has not finished; no row means a project from before M1."""

    __tablename__ = "asset_stage"
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), primary_key=True)
    key: Mapped[str] = mapped_column(String(128))


class Summary(ProjectBase):
    """Hierarchical summaries (ARCHITECTURE.md §8 stage 14): ``shot`` (ref = shot id),
    ``scene`` (one recording; ref = asset id), ``day`` (ref = trip day, 0 = undated) and
    ``trip`` (ref = 0). Shot and scene summaries are composed from the observations; day
    and trip summaries are written by the summarizer model with the trip context."""

    __tablename__ = "summary"
    __table_args__ = (UniqueConstraint("level", "ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(8))
    ref: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)  # themes, highlights, span
    key: Mapped[str] = mapped_column(String(128))  # everything the summary depends on
    context_digest: Mapped[str] = mapped_column(String(16))
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class PhotoGroup(ProjectBase):
    """Photos that belong together (MEDIA_SUPPORT.md §3, ADR 0026): a ``burst`` (photos
    under a second apart, nearly identical) with its recommended best frame, or a
    ``capture`` (photos and the video segments filmed at the same time and place)."""

    __tablename__ = "photo_group"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # burst|capture
    best_segment_id: Mapped[int | None] = mapped_column(Integer)
    provenance_id: Mapped[int] = mapped_column(ForeignKey("provenance.id"))


class PhotoGroupMember(ProjectBase):
    __tablename__ = "photo_group_member"
    group_id: Mapped[int] = mapped_column(ForeignKey("photo_group.id"), primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segment.id"), primary_key=True, index=True)
