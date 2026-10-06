"""Clock correction end to end (M1 step 10a, ADR 0027; S6 acceptance): a drone whose clock
runs 2 h behind the phone gets a +2 h suggestion from matching photos; accepting it moves
its clips to the right trip day without re-analysis."""

from __future__ import annotations

import os
from collections.abc import Iterator
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.devtools.corpus import CorpusGenerator
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.storage.models_project import Asset, MediaFile
from tests.support.photos import jpeg
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]
RATE = Fraction(30000, 1001)
SCENE_S = 20


@pytest.fixture(scope="module")
def trip(
    tmp_path_factory: pytest.TempPathFactory, ffmpeg_bin: FFmpegBinaries
) -> Iterator[tuple[Any, Any]]:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.conftest import SHARED_MODELS

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOSAIC_HOME", str(tmp_path_factory.mktemp("home-clock")))
        if "MOSAIC_MODELS_DIR" not in os.environ:
            mp.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
        mp.setenv("MOSAIC_STT_MODEL", os.environ.get("MOSAIC_STT_MODEL", "small"))
        root = tmp_path_factory.mktemp("clock") / "trip"
        root.mkdir()
        # The drone's clock says 23:00 UTC; the true time is 01:00 UTC the next day.
        CorpusGenerator(root, ffmpeg_bin)._video(
            "DJI_0001.MP4",
            seconds=4 * SCENE_S,
            seed=60,
            scene_seconds=SCENE_S,
            metadata=(
                ("make", "DJI"),
                ("model", "Mini 4 Pro"),
                ("creation_time", "2025-03-01T23:00:00.000000Z"),
            ),
        )
        scene = int(SCENE_S * RATE)
        for k in range(4):  # one phone photo per scene, at the true time
            jpeg(
                root / f"IMG_{k:04d}.JPG",
                seed=60,
                size=(640, 360),
                make="Apple",
                model="iPhone 15 Pro",
                taken=f"2025:03:02 01:00:{k * SCENE_S + 10:02d}",
                offset="+00:00",
                frame=(k * scene + scene // 2, scene),
            )
        # Video against video, a week later (beyond the ±48 h matching window, so these
        # synthetic look-alikes never pair with the drone): the phone filmed what a Nikon,
        # 1 h behind, also filmed.
        gen = CorpusGenerator(root, ffmpeg_bin)
        for name, make, model, when in (
            ("IMG_V001.MOV", "Apple", "iPhone 15 Pro", "2025-03-09T03:00:00.000000Z"),
            ("DSC_0001.MOV", "NIKON CORPORATION", "NIKON Z 6_2", "2025-03-09T02:00:00.000000Z"),
        ):
            gen._video(
                name,
                seconds=4 * SCENE_S,
                seed=70,
                scene_seconds=SCENE_S,
                metadata=(("make", make), ("model", model), ("creation_time", when)),
            )
        # An earlier phone photo sets day 1 of the trip.
        jpeg(
            root / "IMG_9999.JPG",
            seed=61,
            make="Apple",
            model="iPhone 15 Pro",
            taken="2025:03:01 12:00:00",
            offset="+00:00",
        )
        control = ControlDB()
        ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
        project = init_project(control, control.local_principal, root)
        job = submit_analysis(LocalExecutor(JobStore(control.db)), control.local_principal, project)
        assert run_job(control, job, timeout=1200) == "done"
        yield project, control
        project.close()


def _drone(project: Any) -> Asset:
    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == "DJI_0001.MP4"))
        a = s.get(Asset, aid)
        assert a is not None
        s.expunge(a)
        return a


def test_suggest_accept_and_regroup_days(trip: tuple[Any, Any]) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.editing.retrieval import capture_dates, trip_day
    from mosaic.jobs.store import JobStore

    project, control = trip
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    base = f"/api/projects/{project.id}"
    sugg = client.get(f"{base}/devices/suggestions").json()["suggestions"]
    drone = next(d for d in sugg if d["make"] == "DJI")
    offset = drone["suggestion"]["offset_ms"]
    assert abs(offset - 7_200_000) <= 30_000, offset
    assert drone["suggestion"]["verdict"].endswith("behind")
    assert drone["suggestion"]["pairs"] >= 3
    shown = drone["suggestion"]["evidence"]
    assert shown, "S6 shows evidence pairs"
    for e in shown:  # each side of a pair can be shown as a frame
        for side in ("device_sample", "reference_sample"):
            assert e[side] is not None
            assert client.get(f"/api/media/{project.id}/frame/{e[side]}").status_code == 200
    nikon = next(d for d in sugg if (d["make"] or "").startswith("NIKON"))
    assert abs(nikon["suggestion"]["offset_ms"] - 3_600_000) <= 30_000, "video vs video"

    def day() -> int:
        with project.db.session() as s:
            assets = list(s.scalars(select(Asset).where(Asset.kind.in_(("video", "photo")))))
            first = min(capture_dates(assets).values())
            a = _drone(project)
            return trip_day(a.capture_time, Fraction(0), first)

    assert day() == 1, "before: the drone's wrong clock puts it on day 1"
    r = client.put(
        f"{base}/devices", json={"devices": [{"id": drone["id"], "accept_suggestion": True}]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["assets_updated"] == 1
    assert day() == 2, "after: on the right day, immediately"
    a = _drone(project)
    assert a.capture_time_raw == "2025-03-01T23:00:00+00:00", "the file's time is kept"
    job = r.json()["refresh_job"]
    assert run_job(control, job, timeout=300) == "done"
    kinds = {t.kind for t in JobStore(control.db).tasks(job)}
    assert kinds == {"library.moments", "library.clock", "library.summaries"}, "no analysis"
    after = client.get(f"{base}/devices/suggestions").json()["suggestions"]
    done = next(d for d in after if d["id"] == drone["id"])["suggestion"]
    assert done["applied"]
    assert done["verdict"] == "on time"
    # The drone adopted the reference's zone; a hand nudge afterwards keeps it.
    zone = next(
        d for d in client.get(f"{base}/devices").json()["devices"] if d["id"] == drone["id"]
    )
    assert zone["utc_offset_min"] == 0
    nudge = {"devices": [{"id": drone["id"], "clock_offset_ms": offset + 60_000}]}
    r = client.put(f"{base}/devices", json=nudge)
    assert r.status_code == 200
    after_nudge = next(d for d in r.json()["devices"] if d["id"] == drone["id"])
    assert after_nudge["utc_offset_min"] == 0, "the adopted zone survives an adjustment"
    assert run_job(control, r.json()["refresh_job"], timeout=300) == "done"
    a = _drone(project)
    # A rescan keeps the correction (the grouper re-applies the device's offset).
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.media.pipeline import submit_analysis

    rescan = submit_analysis(LocalExecutor(JobStore(control.db)), control.local_principal, project)
    assert run_job(control, rescan, timeout=900) == "done"
    assert _drone(project).capture_time == a.capture_time
    assert day() == 2


def test_device_api_errors(trip: tuple[Any, Any]) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    project, control = trip
    svc = Services.create(control)
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    url = f"/api/projects/{project.id}/devices"
    devices = client.get(url).json()["devices"]
    phone = next(d for d in devices if d["make"] == "Apple")
    put = client.put
    assert put(url, json={"devices": [{"id": 99999, "clock_offset_ms": 0}]}).status_code == 404
    no_sugg = {"devices": [{"id": phone["id"], "accept_suggestion": True}]}
    assert put(url, json=no_sugg).status_code == 409, "the reference has no suggestion"
    huge = {"devices": [{"id": phone["id"], "clock_offset_ms": 10**12}]}
    assert put(url, json=huge).status_code == 422
    neither = {"devices": [{"id": phone["id"]}]}
    assert put(url, json=neither).status_code == 422
    both = {"devices": [{"id": phone["id"], "clock_offset_ms": 0, "accept_suggestion": True}]}
    assert put(url, json=both).status_code == 422
    empty = put(url, json={"devices": []})
    assert empty.status_code == 200
    assert empty.json()["refresh_job"] is None
    svc.leases.open_read_only(project.id)
    ro = {"devices": [{"id": phone["id"], "clock_offset_ms": 0}]}
    assert put(url, json=ro).status_code == 409
