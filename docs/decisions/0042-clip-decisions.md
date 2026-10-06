# 0042 — The owner's clip decisions in the library

- Status: accepted (M2 step 7a)
- Deciders: agent (autonomous; no human gate)

## Context

S10 and S11 let the owner rate clips (1–5 stars), set USE / MAYBE / REJECT, mark a clip "always" or "never" include, and add tags and a note. The keys work per tile, and the BulkBar applies a change to many clips.

ARCHITECTURE.md lists `user_rating`, `user_note`, `user_tag` and `include_rule` tables, but none existed. The only user decision so far was a `Disposition` row with `source = "user"` on one segment (ADR 0013).

Invariant 10 makes all of these hard constraints until reset. M2 acceptance 4 needs filters over 5,000 clips to answer in under 300 ms.

## Options

1. **A user disposition per segment.** A clip-wide decision would write a row for each of the clip's segments. It needs rewriting whenever segments change, and does nothing for a clip that has not been analysed yet.
2. **A per-clip decision row.** A clip-wide decision is one row, read together with the segment decisions.

## Decision

- **Storage.** We chose option 2.
  - **`clip_decision`:** keyed by asset; holds `disposition`, `stars`, `include` (always / never), `note` and `live_motion`. A row with every field empty is deleted.
  - **`clip_tag`:** holds `(asset_id, tag)`. Tags are trimmed, 1–60 characters, at most 50 per clip.
  - **Migration:** `a8d2c5e7f190`.
- **Precedence per segment.** The first that applies wins:
  1. the clip's `never`, which means REJECT whatever else was decided (the X key's promise: "keeps the clip out of every edit");
  2. the segment's own user disposition;
  3. the clip's `always` (USE), else the clip's disposition;
  4. the analysis.

  `library.decisions.for_segments` is the reference. Three other places state the same rule for speed: the SQL tile status (`browse.status_table`), the critic's rejected set (`decisions.user_rejected`, plus the AI REJECTs the owner did not override) and the cover. A property test compares the SQL with `for_segments` over random combinations.
- **Tile status edge.** A segment with no disposition at all (not yet analysed) takes no part in the SQL tile status, although editing treats it as USE. A clip whose analysed segments are all REJECT shows REJECT until the rest are analysed.
- **A kept clip forces one moment, not all.** A clip-wide USE or always keeps every one of its segments as a candidate and forces only its best (similarity pick, then quality) into the edit (`user_use`). Forcing every segment would make one long clip fill the edit. A user USE on a single segment still forces that segment.
- **Stars, tags and notes are library information.** Editing does not read them yet. S14's edit wizard (M4) may use them as preferences.
- **Tiles and filters.**
  - Each library item carries `status_shown`, the best effective status of its segments: USE over MAYBE over REJECT. An unanalysed clip shows its own decision.
  - `decided_by` is the source of that winning status: `user` for a segment or clip decision, `ai` for the analysis, and the owner's when tied. It drives the AI-vs-you chip (invariant 15).
  - Each item also carries the `decision` fields.
  - Filters run in SQL over a per-asset status subquery: status, stars, camera, day, tag, include and kind.
  - Clips shown as REJECT are hidden by default (S10), and counted in `rejected_hidden`.
  - Day labels keep the trip's numbering under any filter.
- **`clip.updated`.** It is published by an in-process `EventHub` and delivered by the SSE stream.
  - Each stream subscribes a bounded queue, unsubscribed when it ends. A stream that falls behind gets one refetch marker in place of its backlog.
  - A bulk change of more than 200 clips sends one event with `asset_id: null`, so the screen refetches.
- **Home card cover.** It skips clips rejected or excluded as a whole.

## Consequences

- **Re-segmentation.** Segment-level decisions keep their anchors (ADR 0013), and clip decisions need nothing at all.
- **Reports.** The S17 report of rejected clips (step 8) must add clip-level rejections to its segment list.
- **Events.** The hub is per process, matching the single-process server. Distributed workers stay out of scope (CLAUDE.md).
- **Similar grouping.** The library's `group=similar` waits for S10, which decides whether it needs it.
