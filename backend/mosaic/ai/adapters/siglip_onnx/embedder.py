"""Local SigLIP image embeddings via ONNX Runtime (ARCHITECTURE.md §8 stage 9): the
``Embedder`` capability's ``siglip-onnx`` adapter.

Model: ``google/siglip-base-patch16-224`` (Apache-2.0), ONNX conversion
``Xenova/siglip-base-patch16-224`` at a pinned revision. ``base`` (fp32) is the default;
CI uses the smaller ``quantized`` variant. No PyTorch is needed.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

from mosaic.core.paths import models_dir

REPO = "Xenova/siglip-base-patch16-224"
REVISION = "4649052661e53c7000355844105f8a1792088239"
VARIANTS = {"base": "onnx/vision_model.onnx", "quantized": "onnx/vision_model_quantized.onnx"}
# The text tower of the same weights, for search queries (ARCHITECTURE.md §12).
TEXT_VARIANTS = {"base": "onnx/text_model.onnx", "quantized": "onnx/text_model_quantized.onnx"}
TOKENIZER = "tokenizer.json"
MAX_TOKENS = 64  # SiglipTokenizer model_max_length; padded with </s> (id 1), lower-cased
PAD_ID = 1
PROVIDER = "siglip-onnx"
SIZE = 224
DIM = 768

F32 = npt.NDArray[np.float32]


def model_id(variant: str) -> str:
    """Identifies weights exactly; part of artifact keys and the vector index name."""
    return f"siglip-base-patch16-224/{variant}@{REVISION[:12]}"


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


class SiglipEmbedder:
    """``Embedder`` adapter ``siglip-onnx``; the ONNX session loads on first ``embed``."""

    provider = PROVIDER
    dim = DIM

    def __init__(self, variant: str) -> None:
        if variant not in VARIANTS:
            raise ValueError(f"unsupported SigLIP variant {variant!r}; use {sorted(VARIANTS)}")
        self.variant = variant
        self.model = model_id(variant)
        self._session: Any = None
        self._text: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._session is None:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(
                REPO,
                VARIANTS[self.variant],
                revision=REVISION,
                cache_dir=str(models_dir() / "siglip"),
            )
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
            self._session = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
        return self._session

    def _load_text(self, local_only: bool = False) -> tuple[Any, Any]:
        """The text tower. ``local_only`` never downloads (HTTP handlers): a missing model
        raises ``FileNotFoundError``; the search index job fetches it beforehand."""
        if self._text is None:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer

            cache = str(models_dir() / "siglip")
            try:
                model = hf_hub_download(
                    REPO,
                    TEXT_VARIANTS[self.variant],
                    revision=REVISION,
                    cache_dir=cache,
                    local_files_only=local_only,
                )
                tok = hf_hub_download(
                    REPO, TOKENIZER, revision=REVISION, cache_dir=cache, local_files_only=local_only
                )
            except FileNotFoundError:  # LocalEntryNotFoundError: not downloaded yet
                raise
            except OSError as exc:
                raise FileNotFoundError(f"SigLIP text model not available: {exc}") from None
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
            self._text = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
            tokenizer = Tokenizer.from_file(tok)
            tokenizer.enable_truncation(MAX_TOKENS)
            tokenizer.enable_padding(length=MAX_TOKENS, pad_id=PAD_ID, pad_token="</s>")
            self._tokenizer = tokenizer
        return self._text, self._tokenizer

    def has_text_model(self) -> bool:
        """The text tower and tokenizer are on this computer (no network)."""
        from huggingface_hub import try_to_load_from_cache

        cache = str(models_dir() / "siglip")
        return all(
            isinstance(try_to_load_from_cache(REPO, f, revision=REVISION, cache_dir=cache), str)
            for f in (TEXT_VARIANTS[self.variant], TOKENIZER)
        )

    def embed_text(self, texts: Sequence[str], local_only: bool = False) -> F32:
        """L2-normalized text embeddings in the image space, shape (n, 768)."""
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        with self._lock:
            session, tokenizer = self._load_text(local_only)
            ids = np.asarray(
                [e.ids for e in tokenizer.encode_batch([t.lower() for t in texts])],
                dtype=np.int64,
            )
            (pooled,) = session.run(["pooler_output"], {"input_ids": ids})
        vec = np.asarray(pooled, dtype=np.float32)
        out: F32 = vec / np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12)
        return out

    def embed(self, images: Sequence[Image.Image]) -> F32:
        """L2-normalized image embeddings, shape (n, 768)."""
        if not images:
            return np.zeros((0, DIM), dtype=np.float32)
        with self._lock:
            (pooled,) = self._load().run(["pooler_output"], {"pixel_values": preprocess(images)})
        vec = np.asarray(pooled, dtype=np.float32)
        norms = np.linalg.norm(vec, axis=1, keepdims=True)
        out: F32 = vec / np.maximum(norms, 1e-12)
        return out
