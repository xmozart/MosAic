"""Media endpoints for the browser (M2 step 4; ADR 0037): proxies with HTTP range
requests, sample frames, filmstrips and waveforms."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from sqlalchemy import select

from mosaic.storage.models_project import Asset, MediaFile, SampleFrame

pytestmark = [pytest.mark.integration, pytest.mark.models]


def _client(control: Any) -> Any:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    return TestClient(app)


def _asset(project: Any, name: str) -> int:
    with project.db.session() as s:
        aid = s.scalar(select(MediaFile.asset_id).where(MediaFile.rel_path == name))
    assert aid is not None
    return aid


def test_proxy_supports_range_requests(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    url = f"/api/media/{project.id}/proxy/{_asset(project, 'speech.mp4')}"
    full = client.get(url)
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes"
    size = len(full.content)
    assert full.content[4:8] == b"ftyp", "an MP4"
    part = client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == full.content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{size}"
    tail = client.get(url, headers={"Range": "bytes=-50"})
    assert tail.status_code == 206
    assert tail.content == full.content[-50:]
    bad = client.get(url, headers={"Range": f"bytes={size + 10}-"})
    assert bad.status_code == 416
    assert client.get(f"/api/media/{project.id}/proxy/999999").status_code == 404


def test_frames_and_filmstrip(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    aid = _asset(project, "speech.mp4")
    with project.db.session() as s:
        kept = list(
            s.execute(
                select(SampleFrame.id, SampleFrame.ticks)
                .where(SampleFrame.asset_id == aid, SampleFrame.kept.is_(True))
                .order_by(SampleFrame.ticks)
            )
        )
    assert len(kept) >= 2
    jpg = client.get(f"/api/media/{project.id}/frame/{kept[0][0]}")
    assert jpg.status_code == 200
    assert jpg.headers["content-type"] == "image/jpeg"
    assert jpg.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/media/{project.id}/frame/99999999").status_code == 404

    strip = client.get(f"/api/media/{project.id}/filmstrip/{aid}", params={"n": 2}).json()
    assert len(strip["frames"]) == 2
    ticks = [f["ticks"] for f in strip["frames"]]
    assert ticks == sorted(ticks)
    assert all(isinstance(t, int) for t in ticks), "exact times"
    assert strip["frames"][0]["sample_id"] == kept[0][0]
    window = client.get(
        f"/api/media/{project.id}/filmstrip/{aid}",
        params={"n": 64, "start_ticks": kept[1][1]},
    ).json()
    assert all(f["ticks"] >= kept[1][1] for f in window["frames"])
    assert len(window["frames"]) == len(kept) - 1


def test_waveform(analyzed_session: Any) -> None:
    project, control = analyzed_session
    client = _client(control)
    aid = _asset(project, "speech.mp4")
    w = client.get(f"/api/media/{project.id}/waveform/{aid}")
    assert w.status_code == 200, w.text
    body = w.json()
    assert body["silent"] is False
    assert body["bucket"] == {"ticks": 400, "tb": "1/8000"}
    peaks = base64.b64decode(body["peaks"])
    assert len(peaks) == body["count"] > 0
    # Exactly one bucket per 400 samples of the proxy's audio, the last one partial.
    from mosaic.media.ffmpeg import builders
    from mosaic.media.ffmpeg.run import run
    from mosaic.media.proxy import load_proxy
    from mosaic.media.tools import media_tools

    pcm = run(media_tools()[0], builders.audio_pcm(load_proxy(project, aid).path, 8000, 1))
    assert body["count"] == -(-(len(pcm.stdout) // 4) // 400)
    assert max(peaks) > 60  # speech after the first second
    with project.db.session() as s:
        silent = s.scalar(
            select(Asset.id).where(Asset.kind == "video", Asset.audio_stream_index.is_(None))
        )
    if silent is not None:
        quiet = client.get(f"/api/media/{project.id}/waveform/{silent}").json()
        assert quiet == {"silent": True, "bucket": None, "count": 0, "peaks": ""}
