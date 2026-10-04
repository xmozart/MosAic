"""Local SigLIP image embeddings via ONNX Runtime (ARCHITECTURE.md §8 stage 9).

Model: ``google/siglip-base-patch16-224`` (Apache-2.0), ONNX conversion
``Xenova/siglip-base-patch16-224`` at a pinned revision. ``base`` (fp32) is the default;
CI uses the smaller ``quantized`` variant. No PyTorch is needed.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from PIL import Image

from mosaic.core.paths import models_dir

REPO = "Xenova/siglip-base-patch16-224"
REVISION = "4649052661e53c7000355844105f8a1792088239"
VARIANTS = {"base": "onnx/vision_model.onnx", "quantized": "onnx/vision_model_quantized.onnx"}
ENV_VARIANT = "MOSAIC_EMBED_VARIANT"
SIZE = 224
DIM = 768

F32 = npt.NDArray[np.float32]


def variant() -> str:
    v = os.environ.get(ENV_VARIANT, "base")
    if v not in VARIANTS:
        raise ValueError(f"{ENV_VARIANT} must be one of {sorted(VARIANTS)}")
    return v


def model_id(v: str | None = None) -> str:
    """Identifies weights exactly; part of artifact keys and the vector index name."""
    return f"siglip-base-patch16-224/{v or variant()}@{REVISION[:12]}"


def preprocess(images: Sequence[Image.Image]) -> F32:
    """SiglipImageProcessor: bicubic resize to 224×224, scale to [-1, 1], NCHW."""
    batch = np.stack(
        [
            np.asarray(
                img.convert("RGB").resize((SIZE, SIZE), Image.Resampling.BICUBIC), dtype=np.float32
            )
            for img in images
        ]
    )
    batch = batch / 255.0 * 2.0 - 1.0
    out: F32 = batch.transpose(0, 3, 1, 2).astype(np.float32)
    return out


class Embedder:
    def __init__(self, v: str | None = None) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        self.variant = v or variant()
        path = hf_hub_download(
            REPO, VARIANTS[self.variant], revision=REVISION, cache_dir=str(models_dir() / "siglip")
        )
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        self._session = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
        self._lock = threading.Lock()
        self.model = model_id(self.variant)

    def embed(self, images: Sequence[Image.Image]) -> F32:
        """L2-normalized image embeddings, shape (n, 768)."""
        if not images:
            return np.zeros((0, DIM), dtype=np.float32)
        with self._lock:
            (pooled,) = self._session.run(["pooler_output"], {"pixel_values": preprocess(images)})
        vec = np.asarray(pooled, dtype=np.float32)
        norms = np.linalg.norm(vec, axis=1, keepdims=True)
        out: F32 = vec / np.maximum(norms, 1e-12)
        return out


_instances: dict[str, Embedder] = {}
_lock = threading.Lock()


def get_embedder() -> Embedder:
    with _lock:
        v = variant()
        if v not in _instances:
            _instances[v] = Embedder(v)
        return _instances[v]
