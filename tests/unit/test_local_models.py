"""Local model downloads (M3; S1; ADR 0058): pinned, verified, resumable, as app jobs."""

from __future__ import annotations

import hashlib
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest

from mosaic.ai import local_models as lm

DATA = {"model.bin": bytes(range(256)) * 4096, "config.json": b'{"ok": true}'}  # ~1 MiB


def _model(sha: dict[str, str] | None = None, name: str = "test-model") -> lm.LocalModel:
    return lm.LocalModel(
        name,
        "transcriber",
        "faster-whisper",
        "test",
        "Test model",
        "acme/test",
        "rev1",
        tuple(
            lm.ModelFile(p, len(b), (sha or {}).get(p, hashlib.sha256(b).hexdigest()))
            for p, b in DATA.items()
        ),
    )


class Server:
    """A fake Hugging Face `resolve` endpoint with Range support and injectable faults."""

    def __init__(self, drop_after: int | None = None, ignore_range: bool = False) -> None:
        self.drop_after = drop_after
        self.ignore_range = ignore_range
        self.requests: list[tuple[str, str | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        rng = request.headers.get("range")
        self.requests.append((name, rng))
        body = DATA[name]
        start = int(rng.split("=")[1].rstrip("-")) if rng and not self.ignore_range else 0
        part = body[start:]
        headers = {"content-range": f"bytes {start}-{len(body) - 1}/{len(body)}"} if start else {}
        if self.drop_after is not None and len(part) > self.drop_after:
            cut = part[: self.drop_after]
            self.drop_after = None  # only once

            def broken() -> Any:
                yield cut
                raise httpx.ReadError("connection dropped")

            return httpx.Response(206 if start else 200, headers=headers, stream=_Stream(broken()))
        return httpx.Response(206 if start else 200, headers=headers, content=part)


class _Stream(httpx.SyncByteStream):
    def __init__(self, gen: Any) -> None:
        self.gen = gen

    def __iter__(self) -> Any:
        yield from self.gen


@pytest.fixture(autouse=True)
def models_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MOSAIC_MODELS_DIR", str(tmp_path / "models"))  # never the shared cache
    return tmp_path / "models"


def _client(server: Server) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(server))


def test_downloads_verify_and_install(models_home: Path) -> None:
    model, seen = _model(), []
    lm.download(model, lambda d, t: seen.append((d, t)), client=_client(Server()))
    assert model.installed()
    assert (models_home / "local" / "test-model" / "model.bin").read_bytes() == DATA["model.bin"]
    assert not list(model.folder.glob("*.part"))
    assert seen[-1] == (model.size, model.size)
    assert all(a[0] <= b[0] for a, b in pairwise(seen)), "progress only grows"


def test_a_dropped_download_resumes_with_a_range_request() -> None:
    model, server = _model(), Server(drop_after=300_000)
    with pytest.raises(httpx.ReadError):
        lm.download(model, lambda d, t: None, client=_client(server))
    part = model.folder / "model.bin.part"
    assert part.stat().st_size == 300_000, "what arrived is kept"
    assert not model.installed()
    lm.download(model, lambda d, t: None, client=_client(server))
    assert model.installed()
    assert ("model.bin", "bytes=300000-") in server.requests


def test_a_server_that_ignores_the_range_restarts_the_file() -> None:
    model = _model()
    with pytest.raises(httpx.ReadError):
        lm.download(model, lambda d, t: None, client=_client(Server(drop_after=1000)))
    lm.download(model, lambda d, t: None, client=_client(Server(ignore_range=True)))
    assert model.installed()
    assert (model.folder / "model.bin").read_bytes() == DATA["model.bin"]


def test_a_checksum_mismatch_is_never_installed() -> None:
    model = _model(sha={"model.bin": "0" * 64})
    with pytest.raises(lm.ChecksumError):
        lm.download(model, lambda d, t: None, client=_client(Server()))
    assert not (model.folder / "model.bin").exists()
    assert not (model.folder / "model.bin.part").exists(), "a retry starts the file over"
    assert not model.installed()


def test_catalog_pins_match_the_adapters() -> None:
    from mosaic.ai.adapters.faster_whisper.transcriber import MODEL_REVISIONS
    from mosaic.ai.adapters.siglip_onnx.embedder import REVISION, TEXT_VARIANTS, TOKENIZER, VARIANTS

    for name, rev in MODEL_REVISIONS.items():
        m = lm.for_choice("faster-whisper", name)
        assert m is not None, name
        assert m.revision == rev
        assert {f.path for f in m.files} >= {"model.bin", "config.json"}
    for variant in VARIANTS:
        m = lm.for_choice("siglip-onnx", variant)
        assert m is not None, variant
        assert m.revision == REVISION
        assert {f.path for f in m.files} == {VARIANTS[variant], TEXT_VARIANTS[variant], TOKENIZER}
    for m in lm.CATALOG.values():
        assert all(len(f.sha256) == 64 and f.size > 0 for f in m.files)
    # S1's sizes: speech (medium) about 1.5 GB, image understanding about 0.8 GB.
    assert 1.4e9 < lm.CATALOG["whisper-medium"].size < 1.6e9
    assert 0.75e9 < lm.CATALOG["siglip-base"].size < 0.85e9


def test_the_api_runs_the_download_as_an_app_job_that_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs.model import APP_PROJECT
    from mosaic.storage.control import ControlDB
    from tests.support.runner import run_job

    model = _model()
    monkeypatch.setitem(lm.CATALOG, model.name, model)
    server = Server(drop_after=200_000)  # the first attempt loses its connection
    monkeypatch.setattr(lm, "CLIENT", lambda: _client(server))
    control = ControlDB()
    client = TestClient(create_app(Services.create(control)), base_url="http://127.0.0.1")
    row = next(
        r for r in client.get("/api/models/local").json()["items"] if r["name"] == model.name
    )
    assert row["installed"] is False
    assert row["job"] is None
    r = client.post(f"/api/models/local/{model.name}/download")
    assert r.status_code == 202
    job = r.json()["job_id"]
    again = client.post(f"/api/models/local/{model.name}/download").json()["job_id"]
    assert again == job, "one download at a time"
    from mosaic.jobs.store import JobStore

    assert JobStore(control.db).job(job).project_id == APP_PROJECT  # type: ignore[union-attr]
    assert run_job(control, job, timeout=60) == "done"
    assert model.installed()
    assert ("model.bin", "bytes=200000-") in server.requests, "the retry resumed"
    row = next(
        r for r in client.get("/api/models/local").json()["items"] if r["name"] == model.name
    )
    assert row["installed"] is True
    assert client.post(f"/api/models/local/{model.name}/download").json()["job_id"] is None
    assert client.post("/api/models/local/nope/download").status_code == 404


def test_units_set_the_percentage() -> None:
    from mosaic.jobs.model import JobProgress

    p = JobProgress(1, "_app", "models", "running", None, 0, 1, 0, None, 0.0, None, (750, 1000))
    assert p.pct == 75
    done = JobProgress(1, "_app", "models", "done", None, 1, 1, 0, None, 0.0, None, (1000, 1000))
    assert done.pct == 100


def _ctx(name: str, cancel_after: int | None = None) -> Any:
    import threading
    from types import SimpleNamespace

    cancelled = threading.Event()
    reports: list[tuple[int, int]] = []

    def report(done: int, total: int) -> None:
        reports.append((done, total))
        if cancel_after is not None and done >= cancel_after:
            cancelled.set()

    def check() -> None:
        if cancelled.is_set():
            from mosaic.jobs.context import TaskCancelledError

            raise TaskCancelledError("cancelled")

    return SimpleNamespace(
        params={"name": name},
        report=report,
        cancelled=cancelled,
        check_cancelled=check,
        reports=reports,
    )


def test_one_download_per_model_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from filelock import FileLock

    from mosaic.jobs.registry import DeferTask

    model = _model()
    monkeypatch.setitem(lm.CATALOG, model.name, model)
    server = Server()
    monkeypatch.setattr(lm, "CLIENT", lambda: _client(server))
    model.folder.mkdir(parents=True)
    part = model.folder / "model.bin.part"
    part.write_bytes(DATA["model.bin"][:1000])
    # another attempt holds the lock
    with FileLock(model.folder / ".download.lock"), pytest.raises(DeferTask):
        lm.download_task(_ctx(model.name))
    assert part.read_bytes() == DATA["model.bin"][:1000], "the other attempt's file is untouched"
    assert server.requests == []
    lm.download_task(_ctx(model.name))  # the lock is free again
    assert model.installed()


def test_cancelling_keeps_the_partial_file_for_a_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.jobs.context import TaskCancelledError

    model = _model()
    monkeypatch.setitem(lm.CATALOG, model.name, model)

    class Slow(Server):  # several chunks, so the cancel lands mid-file
        def __call__(self, request: httpx.Request) -> httpx.Response:
            r = super().__call__(request)
            body = r.read()
            chunks = [body[i : i + 65536] for i in range(0, len(body), 65536)]
            return httpx.Response(r.status_code, headers=r.headers, stream=_Stream(iter(chunks)))

    server = Slow()
    monkeypatch.setattr(lm, "CLIENT", lambda: _client(server))
    with pytest.raises(TaskCancelledError):
        lm.download_task(_ctx(model.name, cancel_after=200_000))
    kept = (model.folder / "model.bin.part").stat().st_size
    assert 0 < kept < model.size
    lm.download_task(_ctx(model.name))
    assert model.installed()
    assert ("model.bin", f"bytes={kept}-") in server.requests


def test_a_wrong_range_or_an_oversized_part_restarts_the_file() -> None:
    model = _model()
    model.folder.mkdir(parents=True)
    (model.folder / "model.bin.part").write_bytes(b"x" * (len(DATA["model.bin"]) + 10))
    seen: list[tuple[int, int]] = []
    lm.download(model, lambda d, t: seen.append((d, t)), client=_client(Server()))
    assert model.installed()
    assert min(d for d, _ in seen) >= 0, "progress never goes below zero"

    class WrongRange(Server):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            r = super().__call__(request)
            if request.headers.get("range"):
                r.headers["content-range"] = "bytes 0-9/10"
            return r

    other = _model(name="other-model")
    with pytest.raises(httpx.ReadError):
        lm.download(other, lambda d, t: None, client=_client(Server(drop_after=5000)))
    for f in other.folder.glob("*"):
        if f.name != "model.bin.part":
            f.unlink()
    with pytest.raises(httpx.HTTPError):
        lm.download(other, lambda d, t: None, client=_client(WrongRange()))
    assert not (other.folder / "model.bin.part").exists(), "a wrong range is never appended"
    lm.download(other, lambda d, t: None, client=_client(Server()))
    assert other.installed()


def test_a_failed_download_can_be_retried_from_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.jobs.store import JobStore
    from mosaic.storage.control import ControlDB
    from tests.support.runner import run_job

    bad = _model(sha={"model.bin": "0" * 64})
    monkeypatch.setitem(lm.CATALOG, bad.name, bad)
    monkeypatch.setattr(lm, "CLIENT", lambda: _client(Server()))
    control = ControlDB()
    client = TestClient(create_app(Services.create(control)), base_url="http://127.0.0.1")
    job = client.post(f"/api/models/local/{bad.name}/download").json()["job_id"]
    assert run_job(control, job, timeout=60) == "failed"
    task = JobStore(control.db).tasks(job)[0]
    r = client.post(f"/api/diagnostics/tasks/{task.id}/retry")
    assert r.status_code == 200, r.text


def test_an_app_level_task_has_no_project() -> None:
    from mosaic.jobs.context import NoProject

    with pytest.raises(RuntimeError, match="no project"):
        _ = NoProject().outputs_dir


def test_a_server_error_while_resuming_keeps_the_partial_file() -> None:
    model, server = _model(name="busy-model"), Server(drop_after=4000)
    with pytest.raises(httpx.ReadError):
        lm.download(model, lambda d, t: None, client=_client(server))

    class Busy(Server):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

    with pytest.raises(httpx.HTTPError):
        lm.download(model, lambda d, t: None, client=_client(Busy()))
    assert (model.folder / "model.bin.part").stat().st_size == 4000, "nothing is thrown away"
    lm.download(model, lambda d, t: None, client=_client(server))
    assert model.installed()
    assert ("model.bin", "bytes=4000-") in server.requests
