"""Local model weights: the catalog, verified resumable downloads, and where the adapters
find them (M3; S1; ADR 0058).

Each model is a set of files pinned to a repository revision, a byte size and a SHA-256.
A download streams each file into ``<file>.part`` with HTTP Range requests, so a download
cut short (the app quit, the network dropped) continues where it stopped. A file is renamed
into place only after its size and hash match; a model is installed when every file is in
place with its size. Downloads run as app-level ``models.download`` jobs (invariant 8): a
job left unfinished when the app quit is picked up by the worker on the next launch.

Without an installed copy the adapters keep their M0 behaviour (download through the
Hugging Face cache on first use), so developer and CI caches keep working.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from filelock import FileLock, Timeout

from mosaic.core.paths import models_dir
from mosaic.core.principal import Principal
from mosaic.jobs.context import TaskContext
from mosaic.jobs.executor import Executor
from mosaic.jobs.model import APP_PROJECT, JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.registry import DeferTask, task
from mosaic.jobs.store import JobStore
from mosaic.storage.models_control import Job

HF = "https://huggingface.co"
CHUNK = 1 << 20
TIMEOUT = httpx.Timeout(30.0, read=60.0)


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True)


# The HTTP client downloads use (tests swap in a fake server).
CLIENT: Callable[[], httpx.Client] = _client


class ChecksumError(RuntimeError):
    """A downloaded file is not the pinned file (its .part is deleted; a retry restarts)."""


@dataclass(frozen=True)
class ModelFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class LocalModel:
    name: str  # catalog id
    capability: str  # transcriber | embedder
    provider: str
    model: str  # the provider's model name (faster-whisper "medium", siglip-onnx "base")
    label: str
    repo: str
    revision: str
    files: tuple[ModelFile, ...]

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def folder(self) -> Path:
        return models_dir() / "local" / self.name

    def url(self, f: ModelFile) -> str:
        return f"{HF}/{self.repo}/resolve/{self.revision}/{f.path}"

    def installed(self) -> bool:
        return all(_complete(self.folder / f.path, f.size) for f in self.files)

    def downloaded_bytes(self) -> int:
        """Bytes on disk so far, finished files and partial ones (for progress)."""
        total = 0
        for f in self.files:
            dest = self.folder / f.path
            if _complete(dest, f.size):
                total += f.size
            else:
                part = _part(dest)
                total += min(part.stat().st_size, f.size) if part.is_file() else 0
        return total


def _complete(path: Path, size: int) -> bool:
    return path.is_file() and path.stat().st_size == size


def _part(dest: Path) -> Path:
    return dest.with_name(dest.name + ".part")


def _range_starts_at(r: httpx.Response, start: int) -> bool:
    """A 206 answers the range asked for: ``Content-Range: bytes <start>-…``."""
    return r.status_code == 206 and r.headers.get("content-range", "").startswith(f"bytes {start}-")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(
    model: LocalModel,
    on_progress: Callable[[int, int], None],
    cancelled: Callable[[], bool] = lambda: False,
    client: httpx.Client | None = None,
) -> None:
    """Fetches every missing file, resuming partial ones. ``on_progress(done, total)``
    gets the model's bytes so far. Raises on a network error (the .part stays, a retry
    resumes it) or a checksum mismatch (the .part goes, a retry starts the file over)."""
    own = client is None
    http = client or CLIENT()
    try:
        done = model.downloaded_bytes()
        on_progress(done, model.size)
        for f in model.files:
            dest = model.folder / f.path
            if _complete(dest, f.size):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = _part(dest)
            have = part.stat().st_size if part.is_file() else 0
            if have > f.size:  # not this file: start over (progress counted min(have, size))
                part.unlink()
                done -= f.size
                have = 0
            if have < f.size:
                headers = {"Range": f"bytes={have}-"} if have else {}
                with http.stream("GET", model.url(f), headers=headers) as r:
                    if r.status_code not in (200, 206):  # e.g. 503: keep the .part, retry
                        r.raise_for_status()
                        raise httpx.HTTPError(f"unexpected status {r.status_code}")
                    if have and r.status_code == 200:
                        done -= have  # the server ignored the range: start the file over
                        have = 0
                    elif have and not _range_starts_at(r, have):
                        part.unlink()  # another range than asked for: the retry starts over
                        raise httpx.HTTPError("the server sent another range; retrying")
                    with part.open("ab" if have else "wb") as out:
                        for chunk in r.iter_bytes():  # as received: a drop loses nothing
                            if cancelled():
                                return
                            out.write(chunk)
                            done += len(chunk)
                            on_progress(done, model.size)
            if part.stat().st_size != f.size or _sha256(part) != f.sha256:
                done -= part.stat().st_size
                part.unlink()
                raise ChecksumError(f"{model.name}: {f.path} does not match its checksum")
            os.replace(part, dest)
        on_progress(model.size, model.size)
    finally:
        if own:
            http.close()


def _whisper(name: str, label: str, revision: str, files: tuple[ModelFile, ...]) -> LocalModel:
    return LocalModel(
        f"whisper-{name}",
        "transcriber",
        "faster-whisper",
        name,
        label,
        f"Systran/faster-whisper-{name}",
        revision,
        files,
    )


CATALOG: dict[str, LocalModel] = {
    m.name: m
    for m in (
        _whisper(
            "small",
            "Speech (small)",
            "536b0662742c02347bc0e980a01041f333bce120",
            (
                ModelFile(
                    "config.json",
                    2370,
                    "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
                ),
                ModelFile(
                    "model.bin",
                    483546902,
                    "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
                ),
                ModelFile(
                    "tokenizer.json",
                    2203239,
                    "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
                ),
                ModelFile(
                    "vocabulary.txt",
                    459861,
                    "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
                ),
            ),
        ),
        _whisper(
            "medium",
            "Speech",
            "08e178d48790749d25932bbc082711ddcfdfbc4f",
            (
                ModelFile(
                    "config.json",
                    2257,
                    "3622a2ddc41ec0e0fd4e68c13c6830f03b90c38d89aaad184de02c8c642cf807",
                ),
                ModelFile(
                    "model.bin",
                    1527906378,
                    "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
                ),
                ModelFile(
                    "tokenizer.json",
                    2203239,
                    "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
                ),
                ModelFile(
                    "vocabulary.txt",
                    459861,
                    "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
                ),
            ),
        ),
        _whisper(
            "large-v3",
            "Speech (large, Thorough)",
            "edaa852ec7e145841d8ffdb056a99866b5f0a478",
            (
                ModelFile(
                    "config.json",
                    2394,
                    "a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9",
                ),
                ModelFile(
                    "model.bin",
                    3087284237,
                    "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
                ),
                ModelFile(
                    "preprocessor_config.json",
                    340,
                    "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711",
                ),
                ModelFile(
                    "tokenizer.json",
                    2480617,
                    "6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca",
                ),
                ModelFile(
                    "vocabulary.json",
                    1068114,
                    "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1",
                ),
            ),
        ),
        LocalModel(
            "siglip-base",
            "embedder",
            "siglip-onnx",
            "base",
            "Image understanding",
            "Xenova/siglip-base-patch16-224",
            "4649052661e53c7000355844105f8a1792088239",
            (
                ModelFile(
                    "onnx/text_model.onnx",
                    441332132,
                    "3aa7fdbd20eaa8740cce17bf82913de641fcb632a768fed59f661cdcd0c32553",
                ),
                ModelFile(
                    "onnx/vision_model.onnx",
                    371819850,
                    "f89d41bac7f4d4b87e010a467d93f98689d708916ed22f5a07f96fdfa26f475f",
                ),
                ModelFile(
                    "tokenizer.json",
                    2398744,
                    "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08",
                ),
            ),
        ),
        LocalModel(
            "siglip-quantized",
            "embedder",
            "siglip-onnx",
            "quantized",
            "Image understanding (small)",
            "Xenova/siglip-base-patch16-224",
            "4649052661e53c7000355844105f8a1792088239",
            (
                ModelFile(
                    "onnx/text_model_quantized.onnx",
                    111475220,
                    "ad0329b1f35acc66d8953ff2559ce358da8eb0a7011794cf951523d63a4dbce2",
                ),
                ModelFile(
                    "onnx/vision_model_quantized.onnx",
                    99499129,
                    "ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058",
                ),
                ModelFile(
                    "tokenizer.json",
                    2398744,
                    "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08",
                ),
            ),
        ),
    )
}


def for_choice(provider: str, model: str) -> LocalModel | None:
    """The catalog entry a provider profile needs, if it is a local model we ship."""
    return next((m for m in CATALOG.values() if m.provider == provider and m.model == model), None)


# ------------------------------------------------------------------ jobs


def download_job(name: str) -> JobSpec:
    model = CATALOG[name]
    return JobSpec(
        project_id=APP_PROJECT,
        kind="models",
        params={"name": name},
        tasks=[
            TaskSpec(
                kind="models.download",
                stage="downloading",
                resource_class=ResourceClass.IO,
                params={"name": name},
                label=model.label,
            )
        ],
    )


def active_download(store: JobStore, name: str) -> int | None:
    for job in store.jobs(APP_PROJECT, True, kind="models", limit=50):
        if (job.params or {}).get("name") == name:
            return int(job.id)
    return None


def latest_download(store: JobStore, name: str) -> Job | None:
    """The model's newest download job, running or not (S1 shows a failed one as paused)."""
    for job in store.jobs(APP_PROJECT, None, kind="models", limit=50):
        if (job.params or {}).get("name") == name:
            return job
    return None


def ensure_download(
    store: JobStore, executor: Executor, principal: Principal, name: str
) -> int | None:
    """The model's running download, a new one, or None when it is installed."""
    if CATALOG[name].installed():
        return None
    running = active_download(store, name)
    if running is not None:
        return running
    return int(executor.submit(principal, download_job(name)))


def _installed(ctx: TaskContext) -> bool:
    return CATALOG[str(ctx.params["name"])].installed()


@task("models.download", app_level=True, is_done=_installed)
def download_task(ctx: TaskContext) -> dict[str, Any]:
    """One model. Only one download per model at a time, across processes: two would
    append to the same ``.part`` (a double request, or a lease taken over while the old
    attempt still runs). The OS lock goes away with the process, so a crash leaves none."""
    model = CATALOG[str(ctx.params["name"])]
    model.folder.mkdir(parents=True, exist_ok=True)
    lock = FileLock(model.folder / ".download.lock", timeout=0)
    try:
        lock.acquire()
    except Timeout:
        raise DeferTask(f"{model.name} is already downloading") from None
    try:
        download(model, ctx.report, cancelled=ctx.cancelled.is_set)
    finally:
        lock.release()
    ctx.check_cancelled()
    return {"name": model.name, "bytes": model.size}
