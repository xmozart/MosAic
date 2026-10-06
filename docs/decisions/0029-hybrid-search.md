# ADR 0029 — Hybrid search

- **Status:** accepted (agent decision, M1 step 11)
- **Date:** 2026-10-05

## Context

ARCHITECTURE.md §12 asks for SigLIP text→image similarity over sample embeddings, plus
FTS5 over descriptions, tags and transcripts, merged with reciprocal rank fusion. S12
needs All / Visual / Speech modes, a "matched" reason under each result, and suggestions
taken from the trip's own tags. The API is `/projects/{pid}/search` with
`/search/suggestions`. M1 asks for it over the API and the CLI.

## Decision

- **Text embeddings.** The SigLIP adapter gains `embed_text`, using the text tower of
  the same pinned ONNX conversion (`onnx/text_model[_quantized].onnx`) and its
  `tokenizer.json`. Queries are lower-cased (the tokenizer's `do_lower_case`) and padded
  with `</s>` to 64 tokens. `tokenizers` (Apache-2.0) is now a direct dependency. No new
  weights licence: they are the same Apache-2.0 SigLIP weights.
- **Visual ranking.**
  - The query vector is matched against the `sample` vector index, which holds video
    samples and photos, with the 400 nearest fetched.
  - Each sample maps to the segment whose range holds it (a photo's one-frame segment
    included), and a segment ranks by its best sample.
  - The match reason shows that segment's top subjects.
- **Text ranking.**
  - An FTS5 table (`search_fts`, in `storage/sqlite_fts.py` per the SQLite-only rule)
    holds one row per segment and field: `visual` (description), `tags` (subjects and
    issues) and `speech` (the transcript text overlapping the segment).
  - L3 reviews supersede L2 observations, as everywhere else.
  - User text never reaches FTS syntax: words are extracted, quoted and OR-ed with prefix
    matching, and BM25 orders them.
  - The match reason is FTS's snippet ("said: …", "described: …", "tagged: …").
- **Merge.** Reciprocal rank fusion with k = 60 over the visual and text rankings.
  `visual` mode uses embeddings plus descriptions and tags; `speech` mode uses
  transcripts only (no embedder needed); `all` uses everything.
- **Index maintenance.**
  - A project stage `library.search_index` rebuilds the table, asset by asset, when its
    key changes. The key covers observations, reviews, transcripts and segments, with
    their provenance.
  - It runs before summaries and depends only on dispositions. It needs no AI, so a
    summarizer failure never leaves search stale.
  - In Thorough it ends the review chain (the project stage defers), next to the final
    summaries. Balanced deepening ends with it too.
  - The same job fetches the SigLIP text tower and counts the trip's top subjects for
    suggestions, stored in `project_meta`.
- **Queries only read.**
  - A project with no index yet returns no text hits and never creates the table.
  - Search requests never download: the text model is loaded with `local_files_only`.
    If it is missing (no analysis yet, or offline), results are text-only, with
    `visual: "unavailable"` for S12's "analysis incomplete" banner (`ok` when the
    visual ranking ran, `off` in `speech` mode).
  - An index run that could not fetch the text model is not treated as done: the
    stage re-runs until the model is on this computer, so one offline run does not
    leave visual search off.
  - Sample-to-segment mapping is one join per 500 samples, keeping kept samples of
    assets that are ok, and the frames for text-only hits are filled in batches.
- **Results** carry exact segment bounds (`{ticks, tb}`), the frame to show, the
  disposition status, the score and up to three match reasons. Suggestions are the
  trip's most common subjects.
- **Interfaces:** `GET /projects/{pid}/search?q=&mode=&limit=`,
  `GET /projects/{pid}/search/suggestions`, and `mosaic search FOLDER "query"
  [--mode]`.

## Consequences

- Owners can find "the F-35 pass" or "when she said Christmas" across hours of footage,
  and the editor (M2+) can use the same ranking for beat candidates.
- Day summaries and user tags are not in the index yet. Searching them is a later
  addition.
- One-letter words are dropped from text queries, so "F-35" searches "35". Visual
  search usually covers such a query.
- The index rebuild holds the project writer for one transaction. Its duration on the
  40-hour project is measured in step 13.
