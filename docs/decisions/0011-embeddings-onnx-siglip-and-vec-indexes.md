# ADR 0011 — SigLIP on ONNX Runtime, per-kind vector indexes, leader-clustered similarity

- **Status:** accepted (agent decision, M0 step 8)
- **Date:** 2026-10-04

## Context

M0 asks for local SigLIP embeddings ("base in prod, smallest available in CI"), sqlite-vec,
and embedding-only similarity groups. `ARCHITECTURE.md §12` says vector indexes are
"versioned by (model, dimension, analysis version)"; §8 stage 12 says "cluster segments by
embedding … and pick the recommended best per cluster".

Findings while building it:

- PyTorch + transformers would add ~1 GB to the app for one model. ONNX Runtime is already a
  dependency (Silero VAD), and `Xenova/siglip-base-patch16-224` provides ONNX exports of
  Google's Apache-2.0 SigLIP base, including an int8-quantized vision model (99 MB).
- With samples and segments in one index, a segment's nearest neighbours are its own member
  samples; a k-nearest search for similar segments then finds almost no segments.
- Single-linkage (connected components) chains: on the synthetic corpus a quarter of all
  segment pairs are ≥ 0.94 similar, and components spanned most of the trip.

## Decision

1. **Embeddings:** SigLIP base patch16-224 vision encoder through ONNX Runtime (CPU), pinned
   revision. Default `base` (fp32); CI and tests use `quantized` (int8), the smallest
   variant of the same model. `model_id()` names the variant and revision and enters every
   artifact key.
2. **Indexes:** one sqlite-vec `vec0` table per (owner kind, model, dimension): `sample` and
   `segment` vectors never share an index. The analysis version is not in the index name:
   the index is a mirror of the `embedding` table, whose rows are replaced (with their index
   rows) whenever the producing stage's key changes, and every key includes the algorithm
   version. A model change still creates a new index.
3. **Similarity:** leader clustering — segments in descending quality order join the group
   whose seed is nearest within cosine distance 0.06, else become seeds. Seeds are the
   recommended picks. The threshold is calibrated on the real corpus in M0 step 12.
4. **Interim configuration:** like transcription (ADR 0009), the embedding model is chosen in
   code and by `MOSAIC_EMBED_VARIANT` until the provider layer and settings land in step 9.

## Consequences

- No PyTorch in MosAic. Text embeddings for search (M1) use the matching ONNX text encoder.
- `ARCHITECTURE.md §8` stage 12 and §12 are updated.
