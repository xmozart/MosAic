from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.media.ffmpeg.capabilities import FFmpegBinaries, FFmpegNotFoundError, locate


@pytest.fixture(autouse=True)
def _isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Every test gets its own MosAic app-data directory."""
    home = tmp_path_factory.mktemp("mosaic-home")
    monkeypatch.setenv("MOSAIC_HOME", str(home))
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
