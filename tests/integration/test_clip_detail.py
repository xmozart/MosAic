"""S11 clip detail and transcript on the analyzed corpus (ADR 0043)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


def _client(control: Any) -> Any:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


def _asset(project: Any, rel: str) -> int:
    from mosaic.storage.models_project import MediaFile

    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == rel))
    assert aid is not None
    return int(aid)


def _no_floats(value: Any, path: str = "") -> None:
    """Times are exact: every ``ticks`` is an int beside its ``tb`` (invariant 3)."""
    if isinstance(value, dict):
        if "ticks" in value:
            assert isinstance(value["ticks"], int), path
            assert isinstance(value["tb"], str), path
        for k, v in value.items():
            _no_floats(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _no_floats(v, f"{path}[{i}]")


def test_a_speech_clip_in_full(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    aid = _asset(project, "speech.mp4")
    r = client.get(f"/api/projects/{project.id}/clips/{aid}")
    assert r.status_code == 200, r.text
    c = r.json()
    _no_floats(c)
    assert c["name"] == "speech.mp4"
    assert c["proxy_rate"] is not None, "the player steps by the proxy's frames"
    num, den = (int(x) for x in c["proxy_rate"].split("/"))
    assert num / den <= 30.001
    assert c["kind"] == "video"
    assert c["moments"], "a clip with segments has moments"
    first = c["moments"][0]
    assert first["start"]["tb"] == c["duration"]["tb"]
    assert first["status"] in ("USE", "MAYBE", "REJECT")
    assert first["decided_by"] in ("ai", "clip", "user")
    assert set(c["quality"]) == {"sharpness", "steadiness", "exposure", "audio"}
    assert all(v in (None, "Poor", "Fair", "Good", "Excellent") for v in c["quality"].values())
    assert c["quality"]["audio"] is not None, "the clip has sound"
    pos = c["position"]
    assert 1 <= pos["index"] <= pos["count"]
    assert c["transcript"]["segments"] > 0
    assert c["decision"]["stars"] is None
    t = client.get(f"/api/projects/{project.id}/clips/{aid}/transcript").json()
    _no_floats(t)
    words = [w for item in t["items"] for w in item["words"]]
    assert words, "timed words for click-to-seek"
    assert all(w["start"]["ticks"] <= w["end"]["ticks"] for w in words)
    assert t["next_after"] is None
    assert client.get(f"/api/projects/{project.id}/clips/999999").status_code == 404
    assert client.get(f"/api/projects/{project.id}/clips/999999/transcript").status_code == 404


def test_used_in_names_the_edits_that_cut_the_clip(analyzed_session: Any) -> None:
    from mosaic.editing.request import EditRequest
    from mosaic.storage.models_project import EditVersion
    from tests.support.editing import generate

    project, control = analyzed_session
    client = _client(control)
    with project.db.session() as s:
        versions = list(s.scalars(select(EditVersion)))
    if not versions:
        generate(project, control, EditRequest(duration_s=30))
        with project.db.session() as s:
            versions = list(s.scalars(select(EditVersion)))
    events = versions[-1].timeline["tracks"][0]["events"]
    used = int(events[0]["asset_id"][4:])
    c = client.get(f"/api/projects/{project.id}/clips/{used}").json()
    assert c["used_in"], json.dumps(c["used_in"])
    assert {"edit_id", "name", "version"} <= set(c["used_in"][0])


def test_states_no_speech_unsupported_and_photo(analyzed_session: Any) -> None:
    from sqlalchemy import func

    from mosaic.storage.models_project import Asset, PhotoGroup, TranscriptSegment

    project, control = analyzed_session
    client = _client(control)
    base = f"/api/projects/{project.id}/clips"
    with project.db.session() as s:
        spoken = select(TranscriptSegment.asset_id)
        quiet = s.scalar(
            select(Asset.id).where(
                Asset.kind == "video", Asset.status == "ok", Asset.id.not_in(spoken)
            )
        )
        broken = s.scalar(select(Asset.id).where(Asset.status == "unsupported"))
        photo = s.scalar(select(Asset.id).where(Asset.kind.in_(("photo", "live_photo"))))
        bursts = s.scalar(select(func.count(PhotoGroup.id)).where(PhotoGroup.kind == "burst"))
    assert quiet is not None
    c = client.get(f"{base}/{quiet}").json()
    assert c["transcript"]["segments"] == 0
    assert client.get(f"{base}/{quiet}/transcript").json() == {"items": [], "next_after": None}
    assert broken is not None
    u = client.get(f"{base}/{broken}").json()
    assert u["status"] == "unsupported"
    assert u["reason"], "the catalog's reason, never tool output"
    assert u["moments"] == []
    assert u["position"] is None, "the grid does not show unsupported files"
    assert photo is not None, "the corpus has a portrait photo"
    p = client.get(f"{base}/{photo}").json()
    assert p["kind"] in ("photo", "live_photo")
    assert p["proxy_rate"] is None, "photos have no proxy to step through"
    assert p["duration"] is None or isinstance(p["duration"]["ticks"], int)
    if not bursts:
        assert p["burst"] is None, "a single photo has no burst strip"
    else:  # pragma: no cover - the synthetic corpus has no burst
        in_burst = [
            c for c in (client.get(f"{base}/{a}").json() for a in _photo_ids(project)) if c["burst"]
        ]
        assert in_burst, "a burst member shows its strip"
        assert sum(i["best"] for i in in_burst[0]["burst"]["items"]) == 1


def _photo_ids(project: Any) -> list[int]:
    from mosaic.storage.models_project import Asset

    with project.db.session() as s:
        return list(s.scalars(select(Asset.id).where(Asset.kind.in_(("photo", "live_photo")))))


def test_prev_next_follow_the_library_and_the_owner_shows_as_you(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    lib = client.get(f"/api/projects/{project.id}/library", params={"limit": 200}).json()["items"]
    assert len(lib) >= 3
    mid = lib[1]["asset_id"]
    c = client.get(f"/api/projects/{project.id}/clips/{mid}").json()
    assert c["position"]["prev"] == lib[0]["asset_id"]
    assert c["position"]["next"] == lib[2]["asset_id"]
    assert (c["status_shown"], c["decided_by"]) == (lib[1]["status_shown"], lib[1]["decided_by"])
    before = c["ai_status"]
    url = f"/api/projects/{project.id}/clips/{mid}/decision"
    try:
        r = client.patch(url, json={"disposition": "MAYBE"})
        assert r.status_code == 200, r.text
        after = client.get(f"/api/projects/{project.id}/clips/{mid}").json()
        assert after["ai_status"] == before, "the AI's view is kept beside the owner's"
        assert after["decision"]["disposition"] == "MAYBE"
        assert all(m["decided_by"] in ("clip", "user") for m in after["moments"] if m["status"])
        assert after["decided_by"] == "user"
    finally:
        client.patch(url, json={"disposition": None})
