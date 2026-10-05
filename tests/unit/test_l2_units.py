"""Mosaics, vision and dispositions units (M0 step 9c)."""

from __future__ import annotations

import io
import itertools
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image
from sqlalchemy import select

from mosaic.ai.adapters.base import strict_schema
from mosaic.ai.adapters.fake import adapter as fake
from mosaic.ai.client import AIClient
from mosaic.ai.prompts.loader import load
from mosaic.ai.prompts.vision.schema_v1 import Output
from mosaic.ai.registry import limits_for, task_check_ready
from mosaic.core.clock import now_iso
from mosaic.core.settings import ProviderChoice
from mosaic.jobs.context import TaskContext
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.registry import PermanentError
from mosaic.jobs.store import JobStore
from mosaic.library import dispositions as disp
from mosaic.library.mosaics import (
    choose_samples,
    geometry,
    label_time,
    pack,
    render_sheet,
    spread,
    tile_label,
)
from mosaic.library.purge import purge_segments, reattach_user_dispositions
from mosaic.library.vision import SheetSegment, check_answer, observation_data, segment_lines
from mosaic.storage import provenance
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import Asset, Disposition, Segment, Shot
from mosaic.storage.projects import init_project

# ------------------------------------------------------------------ mosaics


def test_geometry_follows_provider_image_limit() -> None:
    geo = geometry("balanced", 1568)
    assert (geo.cols, geo.rows, geo.capacity) == (4, 4, 16)
    width, height = geo.size(4)
    assert width <= 1568
    assert height <= 1568
    assert geo.tile_width % 2 == 0
    assert geo.tile_height % 2 == 0
    # A provider with a larger image budget never gets tiles above the thumbnail size.
    assert geometry("balanced", 4096).tile_width == 640
    big = limits_for(ProviderChoice("vision", "anthropic", "claude-haiku-4-5", "cloud"))
    assert big.max_image_px == 1568  # static: no key needed


def test_spread_and_pack() -> None:
    assert spread(10, 4) == [0, 3, 6, 9]
    assert spread(3, 4) == [0, 1, 2]
    assert spread(5, 1) == [2]
    assert pack([4, 4, 4, 4, 3, 2], 16) == [[0, 1, 2, 3], [4, 5]]
    assert pack([3, 4, 4, 4, 2], 16) == [[0, 1, 2, 3], [4]]  # never split an item
    with pytest.raises(ValueError, match="needs 17"):
        pack([17], 16)


def test_labels_use_logical_source_time() -> None:
    ticks = 134 * 90000 + 27000  # 134.3 s
    assert label_time(ticks, "1/90000") == "00:02:14.3"
    assert tile_label(7, 123, ticks, "1/90000") == "T07 · ast_0123 · 00:02:14.3"
    assert label_time(3600 * 1000 + 999, "1/1000") == "01:00:00.9"


def _jpeg(color: tuple[int, int, int], size: tuple[int, int] = (640, 360)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_render_sheet_burns_labels_and_crops_unused_rows() -> None:
    geo = geometry("balanced", 1568)
    tiles = [(_jpeg((200, 200, 200)), tile_label(i + 1, 1, i * 1000, "1/1000")) for i in range(5)]
    tiles.append((_jpeg((200, 200, 200), (360, 640)), "T06 · ast_0001 · 00:00:05.0"))  # portrait
    data = render_sheet(geo, tiles, used_rows=2)
    with Image.open(io.BytesIO(data)) as im:
        assert im.size == geo.size(2)
        rgb = im.convert("RGB")
        x, y = geo.origin(0)
        label_px: Any = rgb.getpixel((x + 1, y + geo.tile_height - 2))
        assert max(label_px) < 60  # dark label box in the bottom-left corner
        frame_px: Any = rgb.getpixel((x + geo.tile_width // 2, y + geo.tile_height // 3))
        assert min(frame_px) > 150
        px, py = geo.origin(5)
        side: Any = rgb.getpixel((px + 4, py + geo.tile_height // 3))
        assert max(side) < 60  # portrait frame is pillarboxed, not stretched


def _seg(a: int, b: int, ua: int, ub: int, shot: int = 1) -> Any:
    return SimpleNamespace(
        start_ticks=a, end_ticks=b, usable_start_ticks=ua, usable_end_ticks=ub, shot_id=shot
    )


def _sample(sid: int, t: int, shot: int = 1) -> Any:
    return SimpleNamespace(id=sid, ticks=t, shot_id=shot)


def test_choose_samples_prefers_usable_range_and_falls_back_to_nearest() -> None:
    samples = [_sample(i, i * 10) for i in range(10)]  # ticks 0..90
    picked = choose_samples(_seg(0, 100, 20, 80), samples, 4)
    assert [s.ticks for s in picked] == [20, 40, 50, 70]
    assert all(20 <= s.ticks < 80 for s in picked)
    assert [s.id for s in choose_samples(_seg(0, 100, 33, 34), samples, 4)] == [0, 3, 6, 9]
    nearest = choose_samples(_seg(91, 99, 91, 99), samples, 4)
    assert [s.id for s in nearest] == [9]
    # The fallback stays inside the segment's shot even when another shot is nearer.
    near_other = [_sample(1, 125, shot=2), _sample(2, 80, shot=1)]
    assert [s.id for s in choose_samples(_seg(100, 120, 100, 120), near_other, 4)] == [2]


# ------------------------------------------------------------------- vision


def _items() -> list[SheetSegment]:
    return [
        SheetSegment("S1", 11, [(1, 101, 0), (2, 102, 90000)], 0, 180000, False),
        SheetSegment("S2", 12, [(3, 103, 200000)], 180000, 270000, True),
    ]


def _obs(ref: str, best: str, **kw: Any) -> dict[str, Any]:
    base = {
        "segment": ref,
        "description": "A boat crosses a bay.",
        "subjects": ["boat"],
        "shot_type": "wide",
        "camera_motion": "pan",
        "people": "none",
        "interest": "high",
        "composition": "good",
        "issues": [],
        "usable": True,
        "best_tile": best,
    }
    return base | kw


def test_check_answer_requires_each_segment_once_and_own_tiles() -> None:
    ok = Output.model_validate({"segments": [_obs("S1", "T02"), _obs("S2", "T03")]})
    assert check_answer(ok, _items()) == []
    bad = Output.model_validate(
        {"segments": [_obs("S1", "T03"), _obs("S1", "T01"), _obs("S3", "T01")]}
    )
    errors = "\n".join(check_answer(bad, _items()))
    assert "S1: best_tile T03 is not one of T01, T02" in errors
    assert "S1 appears 2 times" in errors
    assert "S2 is missing" in errors
    assert "S3 is not a segment" in errors


def test_observation_resolves_best_tile_to_source_ticks() -> None:
    obs = Output.model_validate({"segments": [_obs("S1", "T02")]}).segments[0]
    data = observation_data(obs, _items()[0], "1/90000")
    assert data["best_frame"] == {
        "tile": "T02",
        "sample_id": 102,
        "time": {"ticks": 90000, "tb": "1/90000"},
    }
    assert "segment" not in data
    assert data["interest"] == "high"


def test_vision_prompt_renders_and_schema_is_strict() -> None:
    prompt = load("vision", 1)
    lines = segment_lines(_items(), "1/90000")
    assert lines.splitlines()[0] == "S1: tiles T01–T02, 00:00:00.0–00:00:02.0 (00:02.0), no speech"
    assert "S2: tiles T03," in lines
    system, user = prompt.render(
        {"asset": "ast_0001", "camera": "GoPro", "tile_count": 3, "segment_list": lines}
    )
    assert "Do not name" in system
    assert "S2: tiles T03" in user
    schema = strict_schema(Output.model_json_schema())
    obs_def = schema["$defs"]["SegmentObservation"]
    assert obs_def["additionalProperties"] is False
    assert "pattern" not in obs_def["properties"]["segment"]
    assert set(obs_def["required"]) == set(obs_def["properties"])
    with pytest.raises(ValueError, match="interest"):
        Output.model_validate({"segments": [_obs("S1", "T01", interest="0.83")]})


def _ctx(tmp_path: Path) -> TaskContext:
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "vision", "fake", "fake-1")
    project = init_project(control, me, tmp_path)
    store = JobStore(control.db)
    store.create_job(
        me,
        JobSpec(project.id, "t", tasks=[TaskSpec("x", "s", resource_class=ResourceClass.AI_API)]),
    )
    leased = store.lease("w", "ai_api")
    assert leased is not None
    return TaskContext(leased, "w", LocalExecutor(store), store, project, control=control)


def test_validate_callback_retries_with_errors_then_fails(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    client = AIClient(ctx)
    seen: list[int] = []

    def once(_answer: Any) -> list[str]:
        seen.append(1)
        return ["S9 is missing"] if len(seen) == 1 else []

    before = len(fake.CALLS)
    client.structured("vision", "healthcheck", 1, {}, validate=once)
    assert len(fake.CALLS) == before + 2
    with pytest.raises(PermanentError, match="S9 is missing"):
        client.structured(
            "vision", "healthcheck", 1, {}, variant=3, validate=lambda _a: ["S9 is missing"]
        )
    ctx.project.close()


def test_vision_readiness_names_the_fix(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    task_check_ready(ctx, "vision")  # fake: ready
    assert ctx.control is not None
    ConfigService(ctx.control).set_provider(
        ctx.control.local_principal, "vision", "anthropic", "claude-haiku-4-5"
    )
    with pytest.raises(NotConfiguredError, match="set-key --provider anthropic"):
        task_check_ready(ctx, "vision")
    ctx.project.close()


# -------------------------------------------------------------- dispositions


def _facts(**kw: Any) -> disp.SegmentFacts:
    base: dict[str, Any] = {
        "usable_seconds": Fraction(5),
        "asset_seconds": Fraction(30),
        "clip_low": [0.0, 0.01],
        "exposure": [120.0, 118.0],
        "obstruction": [0.0, 0.0],
        "sharpness": [(300.0, 0.5), (280.0, 0.5)],
        "shake": [(0.001, 0.5)],
        "shake_floor": 0.004,
        "frozen_fraction": 0.0,
    }
    return disp.SegmentFacts(**(base | kw))


def _codes(reasons: list[disp.Reason]) -> dict[str, str]:
    return {r.code: r.status for r in reasons}


def test_rules() -> None:
    assert disp.rule_reasons(_facts()) == []
    assert _codes(disp.rule_reasons(_facts(asset_seconds=Fraction(6, 5)))) == {
        "accidental_recording": "REJECT"
    }
    assert _codes(disp.rule_reasons(_facts(usable_seconds=Fraction(1, 2)))) == {
        "too_short": "REJECT"
    }
    dark = _facts(clip_low=[0.95, 0.97], exposure=[5.0, 4.0], obstruction=[0.9, 0.9])
    assert _codes(disp.rule_reasons(dark)) == {"black_frames": "REJECT", "obstructed": "REJECT"}
    assert _codes(disp.rule_reasons(_facts(exposure=[20.0, 22.0]))) == {"too_dark": "MAYBE"}
    assert _codes(disp.rule_reasons(_facts(frozen_fraction=0.9))) == {"frozen": "REJECT"}
    assert _codes(disp.rule_reasons(_facts(frozen_fraction=0.4))) == {"partly_frozen": "MAYBE"}
    shaky = _facts(shake=[(0.05, 0.99), (0.04, 0.97)])
    assert _codes(disp.rule_reasons(shaky)) == {"very_shaky": "MAYBE"}
    # Top percentile in a perfectly steady project is not "very shaky".
    assert disp.rule_reasons(_facts(shake=[(0.002, 0.99)])) == []
    blurry = _facts(sharpness=[(5.0, 0.01), (6.0, 0.02)])
    assert _codes(disp.rule_reasons(blurry)) == {"blurry": "MAYBE"}


def test_ai_reasons_and_severity() -> None:
    assert disp.ai_reasons(None) == []
    obs = {"usable": True, "issues": ["pocket_or_covered", "shaky"], "interest": "low"}
    assert _codes(disp.ai_reasons(obs)) == {"pocket_or_covered": "REJECT", "shaky": "MAYBE"}
    dull = {"usable": True, "issues": [], "interest": "low", "composition": "poor"}
    assert _codes(disp.ai_reasons(dull)) == {"low_interest": "MAYBE"}
    assert _codes(disp.ai_reasons({"usable": False, "issues": []})) == {"not_usable": "REJECT"}
    assert disp.decide([]) == "USE"
    assert disp.decide(disp.ai_reasons(obs)) == "REJECT"
    assert disp.decide([disp.Reason("x", "MAYBE", "rule")]) == "MAYBE"


def test_user_dispositions_survive_resegmentation(tmp_path: Path) -> None:
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    with project.write() as s:
        prov = provenance.record(s, provenance.ProvenanceInfo(kind="test"))
        asset = Asset(
            kind="video",
            status="ok",
            profile="generic",
            group_key="a",
            tb="1/1000",
            provenance_id=prov,
            created_at=now_iso(),
        )
        s.add(asset)
        s.flush()
        shot = Shot(
            asset_id=asset.id,
            index=0,
            start_ticks=0,
            end_ticks=9000,
            method="adaptive",
            provenance_id=prov,
        )
        s.add(shot)
        s.flush()

        def segments(bounds: list[tuple[int, int]]) -> list[int]:
            ids = []
            for i, (a, b) in enumerate(bounds):
                g = Segment(
                    asset_id=asset.id,
                    shot_id=shot.id,
                    index=i,
                    start_ticks=a,
                    end_ticks=b,
                    usable_start_ticks=a,
                    usable_end_ticks=b,
                    provenance_id=prov,
                )
                s.add(g)
                s.flush()
                ids.append(g.id)
            return ids

        old = segments([(0, 3000), (3000, 6000), (6000, 9000)])
        for sid, (a, b), source, status, when in (
            (old[0], (0, 3000), "user", "REJECT", "2026-01-01T00:00:00Z"),
            (old[0], (0, 3000), "ai", "USE", now_iso()),
            (old[1], (3000, 6000), "user", "USE", "2026-01-02T00:00:00Z"),
            (old[2], (6000, 9000), "user", "MAYBE", "2026-01-03T00:00:00Z"),
        ):
            s.add(
                Disposition(
                    asset_id=asset.id,
                    segment_id=sid,
                    anchor_start_ticks=a,
                    anchor_end_ticks=b,
                    source=source,
                    status=status,
                    reasons=[],
                    roles=[],
                    updated_at=when,
                )
            )
        s.flush()
        purge_segments(s, asset.id)
        rows = list(s.scalars(select(Disposition)))
        assert {r.source for r in rows} == {"user"}  # AI rows go, user rows stay
        assert all(r.segment_id is None for r in rows)

        new = segments([(0, 4500), (4500, 9000)])
        assert reattach_user_dispositions(s, asset.id) == 2
        by_status = {r.status: r.segment_id for r in s.scalars(select(Disposition))}
        # Newest decision wins a segment; the older one overlapping it stays detached.
        assert by_status == {"REJECT": new[0], "USE": None, "MAYBE": new[1]}
        assert disp.effective(s, new)[new[0]].status == "REJECT"
    project.close()


def test_stage_order_does_not_depend_on_import_order() -> None:
    """Whichever stage module is imported first, every stage's predecessors register
    before it (a stage module imports the modules of the stages it runs after)."""
    import subprocess
    import sys

    from mosaic.jobs.registry import HANDLER_MODULES

    for first in HANDLER_MODULES:
        code = (
            f"import {first}, importlib\n"
            "from mosaic.jobs.registry import HANDLER_MODULES\n"
            "for m in HANDLER_MODULES: importlib.import_module(m)\n"
            "from mosaic.media.inventory import plan_stages\n"
            "plan_stages([1])\n"
        )
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert done.returncode == 0, f"importing {first} first: {done.stderr[-400:]}"


@given(st.integers(1, 500), st.integers(1, 8))
def test_spread_properties(n: int, k: int) -> None:
    idx = spread(n, k)
    assert idx == sorted(set(idx))
    assert len(idx) == min(n, k)
    assert all(0 <= i < n for i in idx)
    if k > 1:
        assert idx[0] == 0
        assert idx[-1] == n - 1


@given(st.lists(st.integers(1, 16), max_size=60))
def test_pack_properties(counts: list[int]) -> None:
    sheets = pack(counts, 16)
    assert [i for sheet in sheets for i in sheet] == list(range(len(counts)))  # order, no split
    assert all(sum(counts[i] for i in sheet) <= 16 for sheet in sheets)
    for a, b in itertools.pairwise(sheets):
        assert sum(counts[i] for i in a) + counts[b[0]] > 16  # a new sheet only when needed


@given(
    st.integers(0, 10**12),
    st.integers(0, 10**6),
    st.sampled_from(["1/90000", "1/1000", "1001/30000"]),
)
def test_label_time_is_monotonic(ticks: int, more: int, tb: str) -> None:
    a, b = label_time(ticks, tb), label_time(ticks + more, tb)
    assert not a.startswith("-")
    assert (len(a), a) <= (len(b), b)
