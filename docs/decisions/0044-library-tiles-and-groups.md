# 0044 — Library tiles, similar grouping and group totals

- Status: accepted (M2 step 7b1)
- Deciders: agent (autonomous; no human gate)

## Context

The S10 mockup and COMPONENTS.md need things the library API didn't provide:
- **Tiles** (`ClipTile`) need a caption, has-speech, a similar count, the AI-vs-you chip and stars.
- **The toolbar** filters by Shot type and Has speech, and groups by Day, Camera or **Similar**.
- **Group headers** read "Day 2 · Arenal / La Fortuna waterfall" with "38 clips · 41 m · 64 photos".

The "Help me label" banner belongs to S24, which is an M4 screen.

## Decision

- **Tile facts** are batched per page (invariant 13):
  - `caption` and `shot_type` come from the vision observation of the clip's most interesting moment: one the analysis did not reject, then interest, quality and similarity pick. These are the AI's own words, so nothing is invented (invariant 16). S11's Why ranks by the AI status first, so on rare clips the two can pick different moments. Both are the analysis's words.
  - `has_speech` is true when any segment has speech.
  - `similar_count` is the number of other clips sharing a similarity group that the grid can show.
- **Filters** are added for `shot_type` (any moment of that shot type) and `has_speech` (true or false). They run as SQL like the others (ADR 0042).
- **`group=similar`** orders clips by their first similarity group, then time. Clips with no similar clips come last, under "No similar clips", and groups are labelled "Similar N".
  - A clip is listed once, under its first group, even if its moments belong to several groups.
  - Keyset paging works as it does for camera grouping.
- **Group totals** are clips, photos and footage seconds (display), under the same filters.
  - Day groups also carry `day` (the trip's number), `date` and the trip context's `place` for that date.
  - The client writes the header from these fields, with the place when there is one and the date otherwise.
- **The S24 banner is not built in M2.** S10 leaves room for it.

## Consequences

- A clip in more than one similarity group appears under only one of them. The inspector's Similar section (ADR 0043) lists all of its look-alikes.
- "Similar N" labels are positional, so the same group can get another number under another filter. Groups have no stable name to show.
- Paging by the similar key, like day paging after a clock correction, can skip or repeat a clip if similarity groups are rebuilt while you scroll. A re-analysis refetches the grid.
- `shot_type` takes the vision schema's values, and an unknown value is a 422.
