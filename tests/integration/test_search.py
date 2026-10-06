"""Hybrid search on the analyzed synthetic corpus (M1 step 11, ADR 0029): speech through
the full-text index, visual through SigLIP text→image, merged by rank fusion."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from mosaic.storage.models_project import Asset, MediaFile, Segment

pytestmark = [pytest.mark.integration, pytest.mark.models]


def _client(control: Any) -> Any:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


def _speech_asset(project: Any) -> int:
    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == "speech.mp4"))
    assert aid is not None
    return aid


def test_speech_search_finds_the_spoken_words(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    url = f"/api/projects/{project.id}/search"
    r = client.get(url, params={"q": "christmas", "mode": "speech"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "the fixture says 'Christmas'"
    top = items[0]
    assert top["asset_id"] == _speech_asset(project)
    assert any(m.startswith("said:") and "christmas" in m.lower() for m in top["matched"])
    assert isinstance(top["start"]["ticks"], int)


def test_visual_and_merged_results(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    base = f"/api/projects/{project.id}"
    visual = client.get(
        f"{base}/search", params={"q": "abstract coloured pattern", "mode": "visual"}
    )
    assert visual.status_code == 200
    items = visual.json()["items"]
    assert items
    assert all(it["sample_id"] is not None for it in items), "a frame to show"
    with project.db.session() as s:
        known = set(s.scalars(select(Segment.id)))
    assert {it["segment_id"] for it in items} <= known
    merged = client.get(f"{base}/search", params={"q": "christmas footage"}).json()["items"]
    assert merged
    scores = [it["score"] for it in merged]
    assert scores == sorted(scores, reverse=True)


def test_query_syntax_is_inert_and_suggestions_are_the_trips_tags(
    analyzed_session: Any,
) -> None:
    project, control = analyzed_session
    client = _client(control)
    base = f"/api/projects/{project.id}"
    for q in ('"NEAR(a b', "*", "segment) OR (1", "--;DROP"):
        r = client.get(f"{base}/search", params={"q": q, "mode": "speech"})
        assert r.status_code == 200, (q, r.text)
    assert client.get(f"{base}/search", params={"q": "x", "mode": "nope"}).status_code == 422
    sugg = client.get(f"{base}/search/suggestions").json()["suggestions"]
    assert "scene" in sugg  # the fake vision's subject


def test_cli_search(analyzed_session: Any) -> None:
    from click.testing import CliRunner

    from mosaic.cli.main import cli

    project, _ = analyzed_session
    out = CliRunner().invoke(cli, ["search", str(project.root), "christmas", "--mode", "speech"])
    assert out.exit_code == 0, out.output
    assert "said:" in out.output


def test_text_and_image_embeddings_agree() -> None:
    import numpy as np
    from PIL import Image

    from mosaic.ai.adapters.siglip_onnx.embedder import SiglipEmbedder

    e = SiglipEmbedder("quantized")
    colours = {"red": (200, 30, 30), "blue": (30, 30, 200), "green": (30, 170, 40)}
    images = e.embed([Image.new("RGB", (224, 224), c) for c in colours.values()])
    texts = e.embed_text([f"a {name} square" for name in colours])
    sim = texts @ images.T
    assert list(np.argmax(sim, axis=1)) == [0, 1, 2], sim


def test_search_reads_only_without_an_index(tmp_path: Any) -> None:
    from mosaic.storage import sqlite_fts
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project

    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path)
    pid = project.id
    project.close()
    client = _client(control)
    r = client.get(f"/api/projects/{pid}/search", params={"q": "anything"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    from mosaic.storage.projects import open_project

    p = open_project(control, control.local_principal, tmp_path, read_only=True)
    with p.db.session() as s:
        assert not sqlite_fts.exists(s), "a query never creates the index"
    p.close()


def test_index_is_skipped_when_unchanged_and_photos_can_match(analyzed_session: Any) -> None:
    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.model import JobSpec
    from mosaic.jobs.store import JobStore
    from mosaic.library.search import search, search_index_spec
    from mosaic.storage.config import ConfigService
    from tests.support.runner import run_job

    project, control = analyzed_session
    store = JobStore(control.db)
    job = LocalExecutor(store).submit(
        control.local_principal,
        JobSpec(project_id=project.id, kind="search", tasks=[search_index_spec()]),
    )
    assert run_job(control, job, timeout=300) == "done"
    events = {e.event for e in store.events(job)}
    assert "skipped_existing" in events, "the analysis already built this index"
    from mosaic.ai.registry import embedder

    emb = embedder(ConfigService(control), control.local_principal)
    with project.db.session() as s:
        photo_segs = set(
            s.scalars(
                select(Segment.id)
                .join(Asset, Asset.id == Segment.asset_id)
                .where(Asset.kind == "photo")
            )
        )
        found = search(s, emb, "a picture", "visual", 200)
    assert found.visual == "ok"
    assert photo_segs & {h.segment_id for h in found.hits}, "photos are searchable too"


def test_offline_search_never_downloads_and_falls_back_to_text(
    analyzed_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import huggingface_hub
    from huggingface_hub.errors import LocalEntryNotFoundError

    from mosaic.ai.adapters.siglip_onnx.embedder import SiglipEmbedder
    from mosaic.library.search import search

    calls: list[dict[str, Any]] = []

    def fake_download(*args: Any, **kwargs: Any) -> str:
        calls.append(kwargs)
        raise LocalEntryNotFoundError("not cached")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_download)
    project, _ = analyzed_session
    emb = SiglipEmbedder("quantized")  # a fresh instance: nothing loaded yet
    with project.db.session() as s:
        found = search(s, emb, "christmas", "all", 20)
    assert calls
    assert all(c.get("local_files_only") is True for c in calls)
    assert found.visual == "unavailable"
    assert found.hits, "speech still matches"


def test_results_show_the_decision_in_force_and_who_made_it(analyzed_session: Any) -> None:
    """S12 tiles follow ADR 0042: a clip decision shows as the owner's, the AI's view is
    kept beside it, and the tile has its name and camera."""
    project, control = analyzed_session
    client = _client(control)
    base = f"/api/projects/{project.id}"
    item = client.get(f"{base}/search", params={"q": "christmas", "mode": "speech"}).json()[
        "items"
    ][0]
    assert item["name"] == "speech.mp4"
    assert item["camera"]["label"]
    assert item["decided_by"] in ("ai", None)
    before_ai = item["ai_status"]
    url = f"{base}/clips/{item['asset_id']}/decision"
    try:
        assert client.patch(url, json={"include": "never"}).status_code == 200
        after = client.get(f"{base}/search", params={"q": "christmas", "mode": "speech"}).json()
        hit = next(i for i in after["items"] if i["segment_id"] == item["segment_id"])
        assert (hit["status"], hit["decided_by"]) == ("REJECT", "user")
        assert hit["ai_status"] == before_ai
        assert client.patch(url, json={"include": None, "disposition": "USE"}).status_code == 200
        kept = client.get(f"{base}/search", params={"q": "christmas", "mode": "speech"}).json()
        hit = next(i for i in kept["items"] if i["segment_id"] == item["segment_id"])
        assert (hit["status"], hit["decided_by"]) == ("USE", "user"), (
            "a clip-wide USE is the owner's"
        )
    finally:
        client.patch(url, json={"include": None, "disposition": None})
