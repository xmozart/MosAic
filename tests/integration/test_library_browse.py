"""Library browsing API (S10; ADR 0031): keyset pages in day or camera order."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from mosaic.storage.models_project import Asset

pytestmark = [pytest.mark.integration, pytest.mark.models]


def _client(control: Any) -> Any:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


def _walk(
    client: Any, url: str, group: str, limit: int, **filters: Any
) -> tuple[list[dict[str, Any]], Any]:
    items: list[dict[str, Any]] = []
    cursor = None
    first_groups = None
    while True:
        params: dict[str, Any] = {"group": group, "limit": limit, **filters}
        if cursor:
            params["cursor"] = cursor
        body = client.get(url, params=params).json()
        if cursor is None:
            first_groups = body["groups"]
        else:
            assert body["groups"] is None, "groups only on the first page"
        items += body["items"]
        cursor = body["next_cursor"]
        if not cursor:
            return items, first_groups


def test_pages_cover_every_shown_clip_once_in_order(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    url = f"/api/projects/{project.id}/library"
    with project.db.session() as s:
        shown = {
            a.id
            for a in s.scalars(select(Asset))
            if a.kind in ("video", "photo", "live_photo") and a.status != "unsupported"
        }
    for group in ("day", "camera", "similar"):
        items, groups = _walk(client, url, group, 3, show_rejected=True)
        ids = [it["asset_id"] for it in items]
        assert len(ids) == len(set(ids)), "no clip twice across pages"
        assert set(ids) == shown
        assert sum(g["count"] for g in groups) == len(shown)
        keys = [g["key"] for g in groups]
        order = [it["group"] for it in items]
        assert order == sorted(order, key=keys.index), "items arrive group by group"
    # By default, clips whose every moment is rejected are hidden, and counted (S10).
    default, _ = _walk(client, url, "day", 100)
    hidden = client.get(url).json()["rejected_hidden"]
    assert len(default) + hidden == len(shown)
    assert all(it["status_shown"] != "REJECT" for it in default)
    items, _ = _walk(client, url, "day", 100, show_rejected=True)
    dated = [it["capture_time"] for it in items if it["capture_time"]]
    assert dated == sorted(dated)
    video = next(it for it in items if it["kind"] == "video" and it["segments"])
    assert isinstance(video["duration"]["ticks"], int)
    assert video["sample_id"] is not None
    # One effective decision per segment, whether the analysis or the user made it.
    assert (
        sum(video["dispositions"].get(k, 0) for k in ("USE", "MAYBE", "REJECT"))
        == (video["segments"])
    )


def test_bad_cursor_and_group_are_rejected(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    url = f"/api/projects/{project.id}/library"
    assert client.get(url, params={"cursor": "not-a-cursor"}).status_code == 422
    first = client.get(url, params={"limit": 1}).json()
    assert first["next_cursor"]
    wrong = client.get(url, params={"group": "camera", "cursor": first["next_cursor"]})
    assert wrong.status_code == 422, "a day cursor does not fit camera order"
    assert client.get(url, params={"group": "nope"}).status_code == 422
    assert client.get(url, params={"limit": 0}).status_code == 422


def test_similar_cursors_and_new_filters_over_http(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    url = f"/api/projects/{project.id}/library"
    day_page = client.get(url, params={"group": "day", "limit": 1}).json()
    bad = client.get(url, params={"group": "similar", "cursor": day_page["next_cursor"]})
    assert bad.status_code == 422, "a day cursor does not page a similar grouping"
    for params in ({"has_speech": True}, {"has_speech": False}, {"shot_type": "wide"}):
        r = client.get(url, params=params)
        assert r.status_code == 200, r.text
    speech = client.get(url, params={"has_speech": True}).json()["items"]
    assert speech, "the corpus has speech"
    assert all(i["has_speech"] for i in speech)
    assert client.get(url, params={"shot_type": "underwater"}).status_code == 422
