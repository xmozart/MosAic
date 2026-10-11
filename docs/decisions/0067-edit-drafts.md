# 0067 — Edit drafts: a storyboard and an undoable op log

- Status: accepted (M4 step 2b)
- Deciders: agent (autonomous; no human gate)

## Context

An edit has a draft, a mutable op log with undo and redo, and immutable versions. A version is made on generation, on an explicit save and before a render (ARCHITECTURE.md §13). S16 shapes the story by moving shots and beats, locking, removing and replacing shots, and undoing any of it. Every draft op must be undoable, and locks must survive regeneration (S16 acceptance). Until M4 an edit had versions only.

## Decision

- **The draft is a storyboard, not a timeline.** A storyboard is the plan's beats in order. Each beat holds its picks in order, including the ones the solver dropped. Each pick keeps a stable `ref` (its selection ref, such as `b2#1`) plus its role, priority, length, audio intent, reason, alternatives and lock.
  - Ops change the storyboard and never a position. The draft is timed by `resolve()` (M4.2a) like any edit, with no AI call, so positions still come only from the solver and refiner (invariant 5).
  - Versions from M4 on store their storyboard in their beats (`beats[].shots`) and the order they were timed in (`timeline.order`). Older versions are rebuilt from their selections in the selector's order.
  - An untouched draft therefore times exactly like its version, and a test checks this.
- **Ops (`edit_draft_op`, one row each, in `seq` order on a base version):**
  - `move_shot` (to an index in any beat) and `move_beat`;
  - `remove_shot`;
  - `lock_shot` (lock or unlock);
  - `replace_shot`, with one of the shot's alternatives or a segment from its beat's pool that is not already in the edit. The replaced segment becomes the first alternative.

  A locked shot cannot be removed or replaced until it is unlocked (invariant 10). Faster and slower per beat come with M4 step 4. Trim waits for M8's trim handles; S16 has none.
- **The owner's order wins once they rearrange.** A move switches the storyboard to its own order (`user_order`): beats as given, shots as given within them. Otherwise the request's chronology would sort a dragged shot back.
  - When the solver backfills a short draft, a spare lands at its place in the beat's order, not at its place in time (`refiner.backfill(by_order=True)`).
  - Lock, remove and replace keep the chronology's order.
- **What the owner takes out stays out.** A removed shot's segment, and the segment a replacement swapped out, go on the storyboard's `excluded` list. The solver never brings them back as spares (`resolve(excluded=…)`), even when another pick names them as an alternative. Swapping back to a segment takes it off the list. Saved versions keep the list in `timeline.excluded`.
- **Undo and redo.** Undo marks the last applied op `undone`. Redo un-marks the first undone op. A new op drops the undone ones, as an editor's undo stack does. Ops on an older base, where a version was made since, are stale and no longer count.
- **Saving.**
  - `POST /edits/{eid}/versions` saves the draft as version N+1: `creator: user`, with the base as its parent. It returns 409 when nothing changed.
  - **The key** is `edit.draft` over everything the timing depends on: the base key, the ops, the candidates' digest, the rate, the rejected segments and the algorithm version (invariant 9).
  - **It is timed in a read session, then committed under the writer.** If a version or op arrived in between, the commit is refused (409, try again). The JSON export is written (invariant 7), the project is checkpointed (snapshots follow edit commits), and the draft is cleared.
- **A changed draft is saved before anything replaces it.** In both cases the save is a `system` version, so unsaved locks and moves are never lost.
  - **Render:** `render.service.version_to_render` saves it as "Saved before render" whenever a render names no version. The API and `mosaic render` both call it, so a render is always of a version (ARCHITECTURE.md §13; invariant 12). A render that saves the draft also needs `edits.write`.
  - **Regenerate:** `submit_generate` saves it as "Saved before regenerate", for the API and `mosaic edit` alike.
- **A pick that is no longer a candidate is left out with a solver note.** This covers a segment re-analysed away, or rejected by the owner since. The owner's later REJECT wins (invariant 10).
- **Drafts are timed in the request.** `GET /draft` and each op answer with the storyboard timed now. Like S14's estimate (ADR 0047), this is a bounded read of retrieval plus the solver, about 150 ms on the 40-hour project. It is not long work, so no job is created (invariant 8).

## Consequences

- S16 (M4 step 14c) and the locks and regeneration steps build on these ops. Locks are flags here. M4 step 3a makes a locked shot keep its exact source range, its frames and its slot in the beat.
- `solver.Shot` has an optional `ref`, so a moved shot keeps its id across versions.
- The `mosaic.edit/1` export gains three additive fields: `beats[].shots` (the storyboard), `timeline.order` (`request` or `user`) and `timeline.excluded`. Readers of older exports are unaffected.
- Until M4 step 3a, regenerating starts again from the AI: the new version keeps none of the owner's locks, moves or exclusions, which remain in the saved version before it. Step 3a carries locks into regeneration.
- Findings as rows (`finding`) come with the critic and findings step (M4 step 10), not here.
