# 0071 — Changing the length, pacing a beat and a shot's alternatives

- Status: accepted (M4 step 4b)
- Deciders: agent (autonomous; no human gate)

## Context

PRODUCT.md §8 lists "change duration", "make a section faster or slower" and "replace one shot from its alternatives". Every action creates a new version and respects locks. M4 acceptance 3: "Make it 90 seconds" creates a new version within tolerance, re-using analysis, and the test verifies that no vision call is made. S16's ShotPopover shows a shot's alternatives with why each was not chosen. API_MAP listed `/shots/{evt}/alternatives`, keyed by event id.

## Decision

- **Changing the length is a storyboard op, `set_duration`.** It is undoable like any other. The draft is re-timed to the new length by the solver and refiner, which drop by priority, trim, extend and backfill from alternatives, with no AI call of any kind. That is stricter than acceptance 3, which only rules out vision.
  - **`POST /edits/{eid}/duration` makes it a version in one step.** Unsaved changes are saved first as a `system` version, then the length change is saved as a `user` version, "Made it 90 s".
    - If a length change is already pending (to this length or another), all pending changes go into this one version instead, with no detour through the pending length.
    - It returns 409 when the edit is already that length; nothing is saved then.
    - The three steps are separate transactions, so an op that lands in between joins the length-change version. That is acceptable for one owner's storyboard.
  - **One candidate set for every draft path.** Retrieval depends on the length: near-duplicates come back when footage is short of three times the target. So the draft view, locking, saving, alternatives and regeneration all read candidates for the draft's own length (`draft.inputs`). A version made to 30 s reloads with exactly the candidates it was timed with.
  - **The edit's request is its current one.** The saved version's request carries the new length, and so does the edit's own request, so a later regeneration keeps it. A default name ("nature · 60 s") follows the length. The consequences:
    - re-running `mosaic edit` with the old length makes a new edit, and with the new length it finds this one;
    - two edits can come to hold the same request, and `create_edit` then picks the older one;
    - reverting to a version (S18, M4 step 11) also restores that version's length on the edit.
  - **When the footage runs short.** When the storyboard's footage cannot fill a longer edit, the version reports it the way the solver always does (`underfilled`, with a note) rather than calling the AI. "Regenerate the whole edit" (ADR 0070) is the way to add clips.
- **A beat faster or slower, `pace_beat`, moves every free shot's length one step** (short, medium, long, hold: the selector's length classes). Locked and absorbed shots keep their cut. Speech shots run to the end of their sentence anyway, so they are not counted. The op is refused when there is no free shot, or when nothing can move further. The solver then fits the beat with the new lengths, and its shots come out shorter (or longer) on the timeline.
- **Alternatives are listed by the shot's storyboard ref, not by event id.** Event ids are positions in one version's timeline and change with every re-timing. A ref is the shot's stable id (ADR 0067). The ref holds `#`, so it is percent-encoded in the path.
  - `GET /edits/{eid}/shots/{shot}/alternatives` lists first the selector's named alternatives, with why each was not chosen. The rest of the beat's pool follows. The list holds only clips that are still candidates and not in the edit or taken out by the owner.
  - Choosing one is the existing `replace_shot` op. The response says whether the shot is locked; `replace_shot` refuses a locked shot until it is unlocked.

## Consequences

- The remaining PRODUCT.md §8 actions (more or less of a content category, a stronger opening, a different ending) are M4 step 4c.
