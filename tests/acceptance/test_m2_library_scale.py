"""M2 acceptance 4, backend half (docs/milestones/M2.md): on a 5,000-clip library, every
filter change returns its first page in under 300 ms. The frontend half (≤ 60 tiles mounted
while 5,000 items scroll) is `frontend/src/features/library/Library.test.tsx`.

The 5,000 clips are clones of a small analysed trip's rows (assets, files, shots,
segments, samples, dispositions), spread over five days with mixed owner decisions and
tags: the library reads only these tables, and analysing 5,000 real clips would take hours.
"""

from __future__ import annotations

import json
import random
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Table, insert, select

from tests.support.runner import run_job

pytestmark = [pytest.mark.acceptance, pytest.mark.models]

TARGET = 5_000
FILTER_S = 0.300
CLIPS = ("A001_basic.mp4", "A002_basic.mp4", "speech.mp4", "shaky.mp4")


def _clone(project: Any, n: int) -> None:
    from mosaic.storage.models_project import ProjectBase

    t: dict[str, Table] = dict(ProjectBase.metadata.tables)
    rng = random.Random(5)
    with project.db.engine.begin() as c:

        def rows(name: str, aid: int) -> list[dict[str, Any]]:
            tab = t[name]
            return [dict(r._mapping) for r in c.execute(select(tab).where(tab.c.asset_id == aid))]

        templates = [
            dict(r._mapping)
            for r in c.execute(
                select(t["asset"]).where(t["asset"].c.status == "ok", t["asset"].c.kind == "video")
            )
        ]
        assert templates, "the small trip was analysed"
        children = {
            a["id"]: {
                k: rows(k, a["id"])
                for k in ("media_file", "shot", "segment", "sample_frame", "disposition")
            }
            for a in templates
        }
        for k in range(n - len(templates)):
            src = templates[k % len(templates)]
            kids = children[src["id"]]
            a = {**src, "group_key": f"{src['group_key']}#clone{k}"}
            del a["id"]
            base = datetime.fromisoformat(a["capture_time"] or "2026-07-15T08:00:00+00:00")
            a["capture_time"] = (base + timedelta(days=k % 5, seconds=7 * k)).isoformat()
            aid = c.execute(insert(t["asset"]).values(**a)).inserted_primary_key[0]
            for f in kids["media_file"]:
                c.execute(
                    insert(t["media_file"]).values(
                        **{
                            **{x: y for x, y in f.items() if x != "id"},
                            "asset_id": aid,
                            "rel_path": f"clones/{k}/{f['rel_path']}",
                        }
                    )
                )
            shots: dict[int, int] = {}
            for s in kids["shot"]:
                shots[s["id"]] = c.execute(
                    insert(t["shot"]).values(
                        **{**{x: y for x, y in s.items() if x != "id"}, "asset_id": aid}
                    )
                ).inserted_primary_key[0]
            segs: dict[int, int] = {}
            for s in kids["segment"]:
                segs[s["id"]] = c.execute(
                    insert(t["segment"]).values(
                        **{
                            **{x: y for x, y in s.items() if x != "id"},
                            "asset_id": aid,
                            "shot_id": shots.get(s["shot_id"]),
                            "similarity_group_id": None,
                        }
                    )
                ).inserted_primary_key[0]
            sample_rows = [
                {
                    **{x: y for x, y in s.items() if x != "id"},
                    "asset_id": aid,
                    "shot_id": shots.get(s["shot_id"]),
                    "dup_of": None,
                }
                for s in kids["sample_frame"]
            ]
            if sample_rows:
                c.execute(insert(t["sample_frame"]), sample_rows)
            disp_rows = [
                {
                    **{x: y for x, y in d.items() if x != "id"},
                    "asset_id": aid,
                    "segment_id": segs[d["segment_id"]],
                }
                for d in kids["disposition"]
                if d["segment_id"] in segs
            ]
            if disp_rows:
                c.execute(insert(t["disposition"]), disp_rows)
            roll = rng.random()
            if roll < 0.4:
                c.execute(
                    insert(t["clip_decision"]).values(
                        asset_id=aid,
                        disposition=rng.choice(["USE", "MAYBE", "REJECT", None]),
                        stars=rng.choice([None, 3, 4, 5]),
                        include=rng.choice([None, None, "always", "never"]),
                        updated_at="2026-10-08T00:00:00+00:00",
                    )
                )
            if roll < 0.15:
                c.execute(
                    insert(t["clip_tag"]).values(
                        asset_id=aid, tag=rng.choice(["sunset", "family", "drone"])
                    )
                )


def test_five_thousand_clips_filter_in_under_300_ms(
    corpus_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project

    root = tmp_path / "trip"
    root.mkdir()
    for name in CLIPS:
        shutil.copy2(corpus_dir / name, root / name)
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "all", "fake", "fake")
    project = init_project(control, me, root)
    job = submit_analysis(LocalExecutor(JobStore(control.db)), me, project)
    assert run_job(control, job, timeout=1200) == "done"
    _clone(project, TARGET)
    pid = project.id
    project.close()

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    url = f"/api/projects/{pid}/library"
    first = client.get(url, params={"limit": 100})
    assert first.status_code == 200, first.text
    everything = client.get(url, params={"limit": 1, "show_rejected": True}).json()
    total = sum(g["count"] for g in everything["groups"])
    assert total >= TARGET, total

    day = (
        first.json()["groups"][1]["key"]
        if len(first.json()["groups"]) > 1
        else first.json()["groups"][0]["key"]
    )
    filters: list[dict[str, Any]] = [
        {},
        {"group": "camera"},
        {"status": "USE"},
        {"status": "none"},
        {"min_stars": 4},
        {"tag": "sunset"},
        {"include": "always"},
        {"kind": "video"},
        {"show_rejected": True},
        {"has_speech": True},
        {"shot_type": "wide"},
        {"day": day},
        {"status": "MAYBE", "min_stars": 3, "day": day},
    ]
    times: dict[str, float] = {}
    for f in filters:
        t0 = time.perf_counter()  # one request, as one filter change makes
        r = client.get(url, params={"limit": 100, **f})
        times[json.dumps(f)] = time.perf_counter() - t0
        assert r.status_code == 200, (f, r.text)
    worst = max(times.values())
    print("LIBRARY5K", json.dumps({k: round(v * 1000, 1) for k, v in times.items()}))
    assert worst < FILTER_S, times
