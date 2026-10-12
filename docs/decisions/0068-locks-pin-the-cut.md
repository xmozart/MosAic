# 0068 — A lock pins the shot's cut

- Status: accepted (M4 step 3a)
- Deciders: agent (autonomous; no human gate)

## Context

Locks are hard constraints until the user resets them (invariant 10). M4 acceptance 2 asks that after the owner locks 3 shots and regenerates their beat, the locked shots stay unchanged, at the same relative positions. The solver must also report infeasibility, for example "locked shots exceed target by 22 s". Before M4 a lock was only a flag: the solver never dropped a locked shot, but it still chose the shot's length, and the refiner chose its in and out points. So a locked shot could change from one timing to the next.

## Decision

- **A lock records the shot's cut as it is now (`pin`).** The pin holds its segment, source in and out as SourceTime (`{ticks, tb}`), and its length as TimelineTime (`{frames, rate}`) (invariant 3). Its out point is after its in point, in one time base.
  - **The server fills the pin** when it records the `lock_shot` op, from the draft timed at that moment. A pin sent by the client is ignored.
  - **The recording is checked.** It is refused if the draft changed between timing and writing (`DraftChangedError`, 409), or if the shot's segment is no longer the one the pin names.
  - **Replay.** The op log replays the pin as recorded, so later library or solver changes never move a locked shot.
  - **When a pin stops applying.** If the segment was re-analysed into another time base, or the edit's rate changed, the shot stays locked but is cut afresh, with a solver note.
  - **A dropped shot.** A shot the solver had dropped is locked without a pin: it is kept but not pinned.
- **The solver and the refiner keep a pinned shot exactly.**
  - The solver budgets it at its own length and never trims, extends or drops it.
  - The refiner uses its range as recorded, with no snapping.
  - The jump-cut fixer never merges, moves or drops it.
  - The other shots absorb every adjustment, and landing on the target already skipped locked shots.
- **Two picks cut as one take.** When the refiner had merged two adjacent segments into one event, locking either pick pins the whole event to it.
  - The other pick is *absorbed*. It is timed inside the locked cut, and the event keeps it in `origin.merged` and `merged_segments` and in `selections`. Its footage counts as in the edit, so it is never added again as a spare.
  - An absorbed pick cannot be moved, removed, replaced or locked on its own until the lock is released. Unlocking releases it.
  - If the locked pick is gone from the library, its absorbed picks are timed on their own, with a note.
- **Infeasibility is measured in frames.** `metrics.locks` gives the number of locked shots, how many are pinned, the pinned frames (a lock without a cut is not budgeted), and `over_frames`: how far past the longest edit allowed (target plus tolerance) they go, or 0 when they fit. When they don't fit, the first solver note says by how much. The UI states it in time ("Locked shots add up to 5:22"). The solver still keeps every lock, so the edit runs long rather than breaking a lock.
- **Relative position.** A locked shot keeps its place in its beat's storyboard order. Regenerating a beat (M4 step 3b) keeps each locked shot at its ordinal slot among the beat's picks.

## Consequences

- Version storyboards (`beats[].shots`) carry `pin` and `absorbed_by`, so a lock survives saves and every later version made from them.
- A version saved from a draft keeps its whole storyboard, including picks whose segment is gone from the library. They are left out of the timing with a note, and come back if the segment does. Before M4.3a, such picks fell out of the next version's storyboard.
- S14's infeasible-locks warning needs the edit's locks. Wizard steps for an existing edit ("Change settings") pass the edit's id to the estimate in M4 step 14a. A brand-new edit has no locks. *(Superseded by ADR 0093: "Change settings" starts a new edit (ADR 0088), and the lock warning is S16's.)*
- Pins are in the source's ticks and the timeline's frames at the edit's rate. The rate is fixed per edit until the owner changes the request's frame rate. That change is a regeneration, which re-times pinned shots from their source range (step 4).
