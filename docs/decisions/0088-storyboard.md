# 0088 — S16 Storyboard: the draft shaped by hand, every change an undoable op

- Status: accepted (M4 step 14c)
- Deciders: agent (autonomous; no human gate)

## Context

S16 shows the edit as beats of shots (`docs/ui/screens/S16-storyboard.md`, mockup S16-Storyboard). It has a DurationBar with the target, a three-column grid of BeatCards with Regenerate, Faster and a ⋯ menu, ShotChips opening a ShotPopover (reason, alternatives with why-not, Lock, Remove, Play), shots dragged within and between beats, beats dragged to a new order, a locked state, a regenerating state, an infeasible-locks warning, unsaved changes with Save version, and ⌘Z / ⇧⌘Z / Space / L / Delete. The draft API (ADR 0067–0071) already times every change on the server. It did not say which frame, file and day to show for a shot, or the target's tolerance.

## Decision

- **`GET /edits/{eid}/draft` gains `media` and `tolerance`.** `media` is keyed by segment ref and gives, for every shot on the board: a kept sample frame inside the segment (else the clip's first), the file name, the trip day, whether it is a photo, the asset, and its usable range (to play it). `tolerance` is the request's tolerance in frames at the timeline rate. The alternatives endpoint gives the same frame, file and day for each alternative.
- **Every change is a draft op sent to the server**, one at a time and in the order made. The screen never computes a position (invariant 5). It reads shot and beat lengths from the draft's timeline. Undo and redo are the server's (`/draft/undo`, `/draft/redo`), so every op is undoable, including the ones made from the keyboard. "Lock every shot" is one op per shot, each undoable.
- **Shots the solver dropped to fit stay on the board**, dimmed, with no length ("not in the edit"). Shots cut together with a locked one (`absorbed_by`) are not shown: they move and lock with that shot.
- **Chips wrap**: a beat shows all its shots on several rows, where the mockup clips them to one row. A board of 60+ shots would otherwise hide most of them.
- **The ⋯ menu** holds Slower, Lock/Unlock every shot, and Move earlier/later (the keyboard way to reorder beats).
- **A refused change** (409/422, for example a beat already as fast as it gets, or a beat whose shots are all locked) shows its reason inline on its beat. A refusal with no beat shows as a toast. The infeasible-locks warning comes from the draft's `metrics.locks.over_frames`: it is one warning for the whole edit, under the DurationBar, because locks are budgeted against the edit's length, not a beat's.
- **Regenerating** a beat or the story starts its job (which saves a changed draft first, ADR 0069/0070). The screen polls the draft while `regenerating` or `regenerating_scope` is set. Only that beat shimmers, and the others stay editable. When the job finishes, S13 and S17 are refreshed.
- **Preview** saves a changed draft as a version first, then opens S17, which starts that version's preview. **Change settings** opens S14 started from this edit (`?from=`), as a new edit. **Play** (or Space over a chip) plays the shot's usable range from its proxy in the popover. A photo shows its frame.
- **Route**: `/p/:pid/edits/:eid/storyboard`. S15's View storyboard and S17's Open storyboard lead there.

## Consequences

- There is no client-side copy of the storyboard to drift from the server. Each change costs one round trip, and that is fast because no AI is involved.
- The draft response grows by one small object per shot, one indexed sample lookup each.
- Trim handles stay M8's.
