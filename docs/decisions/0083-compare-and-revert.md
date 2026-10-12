# 0083 — Compare by shot ref, revert as a copy, renders reused by assembly key

- Status: accepted (M4 step 11)
- Deciders: agent (autonomous; no human gate)

## Context

M4 asks for "version compare (event list diff and side-by-side preview), and revert", and acceptance 5: "Reverting to v1 after 5 versions yields a render identical to the original v1 render (chunk cache hash match)." S18 shows "What changed" with Replaced / Trimmed / Moved / Removed tags and timecodes, and says reverting "creates a new version, never a destructive change" whose render is a cache hit. Versions are immutable (ADR 0067); chunks are cached by event and profile (ARCHITECTURE §10).

## Decision

- **Revert** (`POST /edits/{eid}/revert {version}`) makes version N+1 equal to the chosen one: the same timeline, beats, request, rate, findings and key; metrics note `reverted_from`; `creator: user`, reason "Reverted to vK", parent the latest version. Nothing earlier changes. The storyboard's unsaved changes (on the version being left) are dropped, the edit's current request follows the version (length and weights, as a save does), its findings get rows of their own, and the project is snapshotted.
- **Compare** (`GET /edits/{eid}/compare?a&b`) matches shots by their storyboard refs, which stay with a shot across versions (title cards are left out):
  - `replaced`: the ref holds another clip; `trimmed`: the same clip with another source range; `moved`: out of the longest order both versions share (a replaced or trimmed shot may be flagged `moved` too; which of two swapped shots moved is that order's choice); `added` and `removed`.
  - Each change carries both event ids, both segments and the frame where it is (in b, or in a for a removed one); `same` says the timelines are identical.
- **Render reuse.** Chunks are reused by their keys already, so a reverted version renders no chunk again. On top of that, a render's **assembly key** (its chunk keys in order with its dissolves, its audio chunks, the music track as it is on disk, its length and profile) is stored in its metrics; a render whose key matches a finished render of the same edit hard-links (or copies) that file instead of assembling, and notes `reused_from`. A revert's render is then the same file, byte for byte.
- The side-by-side preview is S18's two players over the two versions' previews (step 14f).

## Consequences

- M4 acceptance 5 holds by construction and is tested: same chunk keys, no new chunk, the same assembly key and the same bytes.
- Reverting is cheap and safe to undo: it is one more version, and the one left behind stays.
