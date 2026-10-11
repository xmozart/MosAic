# 0070 — Regenerating the story or the whole edit, keeping locks

- Status: accepted (M4 step 4a)
- Deciders: agent (autonomous; no human gate)

## Context

PRODUCT.md §8 offers "regenerate the whole edit, the story only, or one beat", and every action keeps the owner's locks (invariant 10). ADR 0069 covers one beat. The original `edit.generate` re-plans from scratch, keeps no lock, and with an unchanged request it reuses the same version. Neither PRODUCT.md nor S16 says how "the story only" differs from "the whole edit".

## Decision

- **"The whole edit" (`scope=all`)** is a new plan and a new selection from every candidate, except the clips the owner took out.
- **"The story only" (`scope=story`)** is a new plan and selection made only from the clips the edit has now. It is a new structure (beats, their order, titles and shares, and which shot goes where) from the same footage, with no new clip.
- **Both use the existing prompts,** planner v2 and selector v2, and the same validation. They run as a job: `POST /edits/{eid}/regenerate?scope=story|all` returns 202 (invariant 8). A changed draft is saved first, and a storyboard change during the job is saved and the take redone, as in ADR 0069.
- **Each take is fresh.** The AI variant is `-1 - pair(pair(scope, take), request variant)`, where `pair` is a Cantor pairing that is never the same for two different pairs. It replaces 0069's `take × 1000 + variant`.
  - Regenerating asks again, and a redo replays the cache.
  - A story take and a whole-edit take never share a cached answer.
  - A regeneration never reuses the answer of another edit made with `--variant N`: that variant is never negative, and these always are.
- **Locks are carried into the new storyboard.** Each locked shot keeps its ref, its pin and its absorbed picks:
  - where the new selection placed its clip, that pick becomes the locked shot;
  - otherwise it goes into the beat whose pool holds the clip, else into the beat of the shot filmed just before it, in time order within that beat;
  - the new selection's own picks of an absorbed clip are dropped;
  - the owner's exclusions carry over, and the new story starts in the request's chronology, not a user order.
- **New picks get refs that no version of the edit has used** (ADR 0069).
- The version is an `ai` version: "Regenerated the story" or "Regenerated the whole edit". Its `metrics.regenerated` records the scope, the take and the locks kept, and its `metrics.ai` records the planner and the selector.
- `GET /edits/{eid}/draft` reports `regenerating_scope` while such a job runs, alongside the beats being regenerated. `scope` has no default: a client that leaves it out is refused, not given a whole new edit.
- The version's key includes the trip context's digest, which the planner and selector prompts read.

## Consequences

- Locks survive every regeneration that PRODUCT.md §8 lists so far: one beat, the story, and the whole edit. The rest of §8 is M4 steps 4b and 4c:
  - 4b: duration without AI, faster or slower, alternatives;
  - 4c: more or less of a category, stronger opening, different ending.
- `POST /edits/{eid}/generate` stays as it was: it regenerates from the request and reuses an unchanged version (M0 acceptance 5).
