from __future__ import annotations

import os
from pathlib import Path

import platformdirs
import pytest

from mosaic.media.ffmpeg.capabilities import FFmpegBinaries, FFmpegNotFoundError, locate

SHARED_MODELS = Path(platformdirs.user_data_dir("MosAic", appauthor=False)) / "models"


def pytest_configure(config: pytest.Config) -> None:
    """Process-wide guard, before any fixture of any scope: tests never see the owner's
    real MosAic app data, OS keychain or AI providers. Function-scoped ``_isolated_home``
    then gives each test its own home on top of this."""
    import tempfile

    os.environ["MOSAIC_HOME"] = tempfile.mkdtemp(prefix="mosaic-test-home-")
    os.environ.setdefault("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.setdefault("MOSAIC_STT_MODEL", "small")
    os.environ.setdefault("MOSAIC_EMBED_VARIANT", "quantized")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Release the native ML runtimes (ONNX Runtime, CTranslate2) while the interpreter is
    still healthy, then end the process with pytest's own status. Their static
    destructors can race their thread pools at interpreter teardown ("libc++abi:
    recursive_mutex lock failed", SIGABRT) after every test has passed; skipping that
    teardown keeps CI's exit code the tests' exit code. Nothing is masked: the status is
    the one pytest computed."""
    import gc

    from mosaic.ai import registry

    registry._local_instances.clear()
    gc.collect()
    session.config.add_cleanup(lambda: _exit_now(int(exitstatus)))


def _exit_now(status: int) -> None:
    import os
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


@pytest.fixture(autouse=True)
def _isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Every test gets its own MosAic app-data directory and an in-memory keyring."""
    import keyring

    from tests.support.testkeyring import MemoryKeyring

    MemoryKeyring.store.clear()
    keyring.set_keyring(MemoryKeyring())
    # Subprocesses (CLI, auto-started workers) must never reach the real OS keychain.
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    # No test may reach a real AI provider: the SDK is pointed at a closed local port.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    home = tmp_path_factory.mktemp("mosaic-home")
    monkeypatch.setenv("MOSAIC_HOME", str(home))
    if "MOSAIC_MODELS_DIR" not in os.environ:
        # Model weights are shared across tests in MosAic's real app-data directory.
        monkeypatch.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
    monkeypatch.setenv("MOSAIC_STT_MODEL", os.environ.get("MOSAIC_STT_MODEL", "small"))
    monkeypatch.setenv("MOSAIC_EMBED_VARIANT", os.environ.get("MOSAIC_EMBED_VARIANT", "quantized"))
    return home


@pytest.fixture(scope="session")
def ffmpeg_bin() -> FFmpegBinaries:
    try:
        return locate()
    except FFmpegNotFoundError as exc:  # pragma: no cover - environment guard
        pytest.fail(str(exc))


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory, ffmpeg_bin: FFmpegBinaries) -> Path:
    from mosaic.devtools.corpus import CorpusGenerator

    out = tmp_path_factory.mktemp("corpus")
    CorpusGenerator(out, ffmpeg_bin).generate()
    return out


@pytest.fixture(scope="session")
def analyzed_session(corpus_dir: Path, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """A copy of the synthetic corpus analyzed once per session, with its control DB.
    Analysis rows are read-only for tests; edit tests add edits."""
    import shutil

    from mosaic.jobs.executor import LocalExecutor
    from mosaic.jobs.store import JobStore
    from mosaic.media.pipeline import submit_analysis
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB
    from mosaic.storage.projects import init_project
    from tests.support.runner import run_job

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOSAIC_HOME", str(tmp_path_factory.mktemp("home-analyzed")))
        if "MOSAIC_MODELS_DIR" not in os.environ:
            mp.setenv("MOSAIC_MODELS_DIR", str(SHARED_MODELS))
        mp.setenv("MOSAIC_STT_MODEL", os.environ.get("MOSAIC_STT_MODEL", "small"))
        mp.setenv("MOSAIC_EMBED_VARIANT", os.environ.get("MOSAIC_EMBED_VARIANT", "quantized"))
        root = tmp_path_factory.mktemp("analyzed") / "trip"
        shutil.copytree(corpus_dir, root)
        control = ControlDB()
        # All AI runs through the offline fake adapter (ADR 0002 H); never a real provider.
        ConfigService(control).set_provider(control.local_principal, "all", "fake", "fake")
        project = init_project(control, control.local_principal, root)
        job = submit_analysis(LocalExecutor(JobStore(control.db)), control.local_principal, project)
        assert run_job(control, job, timeout=1800) == "done"
        yield project, control
        project.close()


@pytest.fixture(scope="session")
def analyzed_corpus(analyzed_session):  # type: ignore[no-untyped-def]
    return analyzed_session[0]
