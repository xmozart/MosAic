"""Analysis modes (M1 step 4): presets, Custom, stage selection, key stability."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from mosaic.core.keys import artifact_key
from mosaic.core.modes import PRESETS, UnknownModeError, from_params, resolve
from mosaic.library.mosaics import geometry
from mosaic.media import l1
from mosaic.media.proxy import PROXY_BITRATE, PROXY_VERSION, ChapterInfo, ProxyPlan
from mosaic.media.visual import CONFIG, config_for


def test_presets_follow_the_modes_table() -> None:
    q, b, t = PRESETS["quick"], PRESETS["balanced"], PRESETS["thorough"]
    assert (q.proxy, q.sample_interval, q.detector, q.stt_model) == (
        "lrf_or_540",
        Fraction(6),
        "threshold",
        "small",
    )
    assert q.tiles[0] * q.tiles[1] == 24
    assert (b.proxy, b.sample_interval, b.detector, b.tiles, b.stt_model) == (
        "720",
        Fraction(3),
        "adaptive",
        (4, 4),
        None,
    )
    assert t.sample_interval == Fraction(3, 2)
    assert 9 <= t.tiles[0] * t.tiles[1] <= 12
    assert t.stt_model == "large-v3"
    assert t.forced_max_shot < b.forced_max_shot
    assert [m.l3 for m in (q, b, t)] == [False, False, True]
    assert all(m.l2 for m in (q, b, t))


def test_custom_is_balanced_plus_overrides() -> None:
    c = resolve("custom", {"sample_interval": "2", "tiles": [5, 4], "l2": False})
    assert c.name == "custom"
    assert c.sample_interval == Fraction(2)
    assert c.tiles == (5, 4)
    assert c.l2 is False
    assert c.detector == "adaptive"
    with pytest.raises(UnknownModeError):
        resolve("quick", {"sample_interval": "2"})
    with pytest.raises(UnknownModeError):
        resolve("fast")
    with pytest.raises(ValidationError):
        resolve("custom", {"tiles": [1, 9]})
    with pytest.raises(ValidationError):
        resolve("custom", {"sample_interval": "0"})
    with pytest.raises(ValidationError):
        resolve("custom", {"frames": 3})  # unknown parameter
    with pytest.raises(ValidationError):
        resolve("custom", {"stt_model": "tiny"})  # no pinned revision
    with pytest.raises(ValidationError):
        resolve("custom", {"l2": False, "l3": True})  # L3 reviews L2 candidates


def test_job_params_round_trip_and_old_jobs_are_balanced() -> None:
    q = PRESETS["quick"]
    assert from_params({"mode_config": q.model_dump(mode="json")}) == q
    assert from_params({"mode": "balanced"}) == PRESETS["balanced"]
    assert from_params(None) == PRESETS["balanced"]


def test_balanced_keys_are_unchanged_from_m0() -> None:
    """Existing analyses stay valid: Balanced proxy and visual keys hash exactly the
    M0 inputs and config."""
    plan = ProxyPlan(
        asset_id=1,
        chapters=[ChapterInfo("a.mp4", "fp", 0, Fraction(1, 90000), 0, 0, 900, 300)],
        video_index=0,
        audio_index=1,
        color_hint="sdr",
        color_range="tv",
        width=1280,
        height=720,
        source_rate=Fraction(30),
        rate=Fraction(30),
        tb=Fraction(1, 90000),
        duration_ticks=900,
        vfr=False,
    )
    m0 = artifact_key(
        "proxy",
        project_id="p",
        inputs={"files": ["fp"], "v": 0, "a": 1},
        config={
            "w": 1280,
            "h": 720,
            "rate": Fraction(30),
            "color": "sdr",
            "range": "tv",
            "encoder": "enc",
            "bitrate": PROXY_BITRATE,
        },
        version=PROXY_VERSION,
    )
    assert plan.key("p", "enc") == m0
    assert config_for(PRESETS["balanced"]) is CONFIG
    assert config_for(PRESETS["quick"]) != CONFIG


def test_stage_selection_by_level() -> None:
    import importlib

    from mosaic.jobs.registry import HANDLER_MODULES
    from mosaic.media.inventory import plan_stages

    for m in HANDLER_MODULES:
        importlib.import_module(m)

    def stages(mode: Any) -> list[str]:
        return [t.stage for t in plan_stages([1], mode)]

    balanced = stages(PRESETS["balanced"])
    assert balanced == stages(None)
    assert "deep review" not in balanced
    assert {"mosaics", "vision", "dispositions"} <= set(balanced)
    assert balanced[-2:] == ["dispositions", "summaries"]
    thorough = stages(PRESETS["thorough"])
    # Summaries come last: a summarizer failure never cancels an analysis stage.
    assert thorough[-3:] == ["dispositions", "deep review", "summaries"]
    no_l2 = stages(resolve("custom", {"l2": False}))
    assert "mosaics" not in no_l2
    assert "vision" not in no_l2
    assert "dispositions" in no_l2  # rule dispositions are L1
    assert "summaries" not in no_l2


def test_threshold_detector_labels_its_shots() -> None:
    content = [0.0] * 100 + [50.0] + [0.0] * 99
    cuts = l1.threshold_cuts(content, 10)
    assert cuts == [100]
    shots = l1.force_split([0, *cuts], 200, 60, "threshold")
    assert [s[2] for s in shots] == ["threshold", "forced", "threshold", "forced"]


def test_mosaic_geometry_follows_the_mode_tiles() -> None:
    q = geometry(PRESETS["quick"].tiles, 1568)
    assert (q.cols, q.rows, q.capacity) == (6, 4, 24)
    w, h = q.size(q.rows)
    assert w <= 1568
    assert h <= 1568
    t = geometry(PRESETS["thorough"].tiles, 1568)
    assert t.capacity == 12
    assert t.tile_width > q.tile_width


def test_transcriber_model_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.ai import registry

    made: list[str] = []
    monkeypatch.setitem(
        registry.LOCAL_PROVIDERS, ("transcriber", "faster-whisper"), lambda m: made.append(m) or m
    )
    monkeypatch.setattr(registry, "_local_instances", {})

    class Choice:
        provider = "faster-whisper"
        model = "medium"

    class Config:
        def provider(self, *_a: Any) -> Choice:
            return Choice()

    monkeypatch.delenv("MOSAIC_STT_MODEL", raising=False)
    assert registry._local(Config(), None, "transcriber") == "medium"  # type: ignore[arg-type]
    assert registry._local(Config(), None, "transcriber", "small") == "small"  # type: ignore[arg-type]
    monkeypatch.setenv("MOSAIC_STT_MODEL", "tiny")
    assert registry._local(Config(), None, "transcriber", "large-v3") == "tiny"  # type: ignore[arg-type]


def test_scope_query_and_body_validation() -> None:
    from mosaic.app.routers.analysis import Scope, _mode, _parse_scope

    assert _parse_scope(None) is None
    assert _parse_scope("trip") == Scope(kind="trip")
    days = _parse_scope("days:3,2,3")
    assert days is not None
    assert days.deepen().days == (2, 3)
    sel = _parse_scope("selection:7")
    assert sel is not None
    assert sel.deepen().segment_ids == (7,)
    for bad in ("days:", "days:0", "selection:x", "trip:1", "week:1"):
        with pytest.raises(HTTPException):
            _parse_scope(bad)
    with pytest.raises(ValidationError):
        Scope(kind="days", days=[1], segment_ids=[2])
    with pytest.raises(HTTPException):
        _mode("quick", None, Scope(kind="trip"))  # deepening targets Balanced or Thorough
    with pytest.raises(HTTPException):
        _mode("custom", {"tiles": [2, 2]}, Scope(kind="trip"))
    assert _mode("thorough", None, Scope(kind="trip")).l3


def test_plan_stages_by_asset_kind() -> None:
    import importlib

    from mosaic.jobs.registry import HANDLER_MODULES
    from mosaic.media.inventory import plan_stages

    for m in HANDLER_MODULES:
        importlib.import_module(m)

    def per_asset(specs: Any, aid: int) -> list[tuple[str, list[str]]]:
        mine = [(i, t) for i, t in enumerate(specs) if t.params.get("asset_id") == aid]
        names = {i: t.stage for i, t in mine}
        return [(t.stage, [names[d] for d in t.deps]) for _, t in mine]

    specs = plan_stages([1], None, [2])
    video = per_asset(specs, 1)
    photo = per_asset(specs, 2)
    assert "photo" not in {s for s, _ in video}
    assert [s for s, _ in photo] == ["photo", "embed", "photo_segment", "mosaics", "vision"]
    assert dict(photo)["embed"] == ["photo"]
    assert dict(photo)["mosaics"] == ["photo_segment"]
    assert "visual" in dict(video)["embed"]
    assert plan_stages([], None, [2])[-1].stage == "summaries"
    only_video = [t.stage for t in plan_stages([1], None, [])]
    assert "photo" not in only_video
