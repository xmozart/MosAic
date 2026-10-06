"""The offline fake embedder (ADR 0031): selectable, deterministic, content-based."""

from __future__ import annotations

import numpy as np
from PIL import Image

from mosaic.ai.adapters.fake.embedder import DIM, FakeEmbedder


def test_image_vectors() -> None:
    e = FakeEmbedder()
    red, blue = Image.new("RGB", (64, 36), (200, 20, 20)), Image.new("RGB", (64, 36), (20, 20, 200))
    v = e.embed([red, red.copy(), blue])
    assert v.shape == (3, DIM)
    assert v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
    assert np.allclose(v[0], v[1])
    assert not np.allclose(v[0], v[2])
    assert e.embed([]).shape == (0, DIM)


def test_text_vectors_are_deterministic() -> None:
    e = FakeEmbedder()
    a, b = e.embed_text(["Sunset Beach"]), e.embed_text(["sunset beach"])
    assert np.allclose(a, b)
    assert not np.allclose(a, e.embed_text(["mountains"]))
    assert e.embed_text([]).shape == (0, DIM)


def test_selectable_but_never_part_of_all() -> None:
    from mosaic.storage.config import ConfigService
    from mosaic.storage.control import ControlDB

    control = ControlDB()
    config = ConfigService(control)
    me = control.local_principal
    caps = {c.capability for c in config.set_provider(me, "all", "fake", "fake")}
    assert "embedder" not in caps
    assert [c.capability for c in config.set_provider(me, "embedder", "fake", "fake")] == [
        "embedder"
    ]
    from mosaic.ai.registry import embedder

    assert isinstance(embedder(config, me), FakeEmbedder)
