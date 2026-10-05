# ADR 0015 — M0 editing pipeline: retrieval, solver, refiner and metric definitions

- **Status:** accepted (agent decision, M0 step 10)
- **Date:** 2026-10-05

## Context

`ARCHITECTURE.md §9` fixes the stages (retrieval → planner → selector → solver → cut
refiner → deterministic critic → immutable version), and `EVALUATION.md §2` names the
metrics. The spec leaves open: concrete pace numbers, how candidates are capped, how the
AI calls are cut up, how the solver resolves conflicts, how jump cuts are avoided, how edits
are identified, and the exact metric definitions.

## Decision

1. **Identity and idempotency.**
   - An edit has a row id (shown as `edt_0001` in the CLI) and a ULID (`uid`). The ULID is
     the API's `{eid}` and is registered in the control DB's edit index.
   - `mosaic edit` reuses the edit whose request is identical; `--variant N` is part of the
     request, so it starts a new edit.
   - The generation key hashes:
     - the request
     - the candidates' state (segments, observation provenance, dispositions)
     - the timeline rate
     - the planner and selector provider/model and prompt versions
     - `EDIT_VERSION`
   - When the latest version has the same key, no version is created and no AI call is
     made (M0 acceptance 5).
2. **Timeline rate:** the source rate that covers the most duration. High-frame-rate
   (≥ 100 fps) sources are conformed and never set the timeline rate. `--fps` overrides it.
3. **Pace (min / preferred / max seconds; dialogue up to 20 s), stored in frames:**

   | Pace | Min | Preferred | Max |
   |---|---|---|---|
   | very slow | 3 | 7 | 15 |
   | slow | 2.5 | 5.5 | 12 |
   | balanced | 1.5 | 3.5 | 8 |
   | energetic | 1 | 2.5 | 5 |
   | fast | 0.7 | 1.8 | 3.5 |
   | very fast | 0.5 | 1.2 | 2.5 |

   Length classes map onto these values:
   - `short` = max(min, 0.6 × preferred)
   - `medium` = preferred
   - `long` = min(max, 1.6 × preferred)
   - `hold` = max
4. **Retrieval.**
   - Candidates are segments whose effective disposition is not REJECT and whose usable
     range is at least the minimum shot. Only the recommended pick of each similarity
     group qualifies; a user USE always qualifies.
   - If the distinct footage is shorter than 3 × the requested duration, the other group
     members come back, marked "similar to …".
   - The list is capped at 200, shared out by day in proportion to the footage, best first.
5. **AI calls.** One planner call, then one selector call that covers every beat, so no
   clip is used twice and the call stays small. Per-beat regeneration (M2) will call the
   same prompt with one beat. Code-side validation (ADR 0013's `validate` hook) checks:
   - the beat shares add up to 100 ± 5
   - every clip id is a real candidate
   - each beat is answered once
   - no clip is used twice
6. **Solver.**
   - Each shot's desired length is clamped to [min, max] and to its usable range.
   - While the edit is over target + tolerance, the solver drops the lowest-priority shot of
     the beat furthest over its budget, as long as the total stays at or above the target.
     Locked shots, user USE shots and a beat's last shot are never dropped.
   - Lengths are then trimmed or extended frame by frame toward the exact target.
   - Underfill is reported, not hidden.
   - Chronology: `strict` orders by capture time; `mostly` keeps beat order and sorts by
     capture time within a beat; `thematic` and `story` keep the selector's order.
7. **Cut refiner.**
   - Shots are placed around the observation's best frame; dialogue shots start at the
     first sentence.
   - The in point slides up to 1 s past a camera jolt (motion above 2 × the segment
     median).
   - Cuts move out of words.
   - Dialogue shots start at a sentence start. They end at a sentence end, extended when
     the sentence fits, otherwise ended at the previous one.
   - The in point lands on the source frame grid, and the length is a whole number of
     timeline frames.
   - **Jump cuts** are adjacent events from the same recording that overlap or are under
     2 s apart. They are removed in this order:
     - merge, when both are in order within the same take
     - otherwise, swap with a later cut of the same beat, if no new jump cut results
     - otherwise, drop the weaker cut
   - **Backfill:** while the edit is short, spare shots (solver drops and the selector's
     named alternatives) are inserted inside their beat at a jump-free position, nearest
     to their place in time when the edit is chronological.
   - Out points of non-dialogue shots then absorb the last frames so the edit lands on its
     exact target.
8. **Audio defaults:** dialogue at 0 dB, natural sound at −6 dB, ambience
   (`natural_sound_low`) at −14 dB, `mute` off, with 2-frame fades at every cut. When the
   selector asks for "dialogue" on a clip without speech, the clip uses its natural sound.
9. **Metric definitions (zero targets):**
   - **Mid-word cut:** an audible (not muted) event cut that falls inside a word by more
     than 20 ms. Word timestamps are approximate.
   - **Dialogue truncation:** a dialogue-intent event that ends inside a transcript
     sentence. Speech under natural-sound or ambience intent was chosen as sound, not
     dialogue ("without intent", EVALUATION §2).
   - **Adjacent jump cut:** as defined in item 7.
   - **REJECT used:** an event whose segment has an effective REJECT and is not locked.
   - **Duration:** off the target by more than the tolerance.
10. **Versions and export (ARCHITECTURE.md §13).**
    - Each version stores `parent_version`, `creator` (`ai` for generated versions),
      `reason` (`generate` or `regenerate`), its key and its provenance.
    - The JSON export at `edits/edt_NNNN/vNNN.json` carries the key and provenance id, and
      is rewritten if it is missing when an identical generation reuses the version.
    - The selector's alternatives that backfill inserts get their own selection refs
      (`b2#3~alt0`) and reasons, so the report never attributes one clip's reason to
      another.
    - A merged cut takes the union of both segments' usable ranges and speech context.
11. **API (M0 subset).**
    - `POST /projects/{pid}/edits` creates the edit and starts its generation in one call;
      `POST /edits/{eid}/generate` regenerates.
    - The `edit.progress` and `edit.version_created` SSE events come with the UI (M2).
      Until then, job progress covers generation.
    - The report lists effective REJECTs only (user decisions override, invariant 10), one
      page at a time.
12. **Job stage label.** Leasing a task now sets the job's stage to that task's stage, so
    progress never shows an earlier task's sub-stage (seen as a stale "motion" label).

## Consequences

- Edits on the synthetic corpus meet every zero-target metric with the fake AI, and land
  exactly on target.
- The repetition count is high on synthetic footage, because synthetic frames look alike
  to SigLIP. It is calibrated with the similarity threshold in step 12.
- The thresholds above are first estimates, to be tuned on the real corpus in step 12.
- Draft operations, per-beat regeneration and the AI critic (M2+) build on these
  structures. Edit versions stay OTIO-mappable: one video track of clip events with
  integer source and timeline ranges.
