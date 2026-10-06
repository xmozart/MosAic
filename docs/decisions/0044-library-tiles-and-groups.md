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

## Screen (step 7b2)

- **Keys act on the selection,** or on the focused tile when nothing is selected.
  - Grid keys act only when the key comes from the grid. Buttons, fields, menus, group headers and the inspector's player keep their own keys.
  - **/** and **Esc** work anywhere except while typing.
  - **U, M, R and 1–5, 0** set the clip decision.
  - **L and X** set always and never include.
  - **Enter** opens S11. **Space** plays the inspector's player.
  - **⌘A** selects the focused clip's group. **/** focuses search. **Esc** clears the selection.
  - **Shift with an arrow** extends the selection; **Shift-click** selects a range and **⌘-click** toggles one clip.
- **Decisions are optimistic.** Every loaded page shows the owner's style at once, following ADR 0042's precedence (`optimistic()`). The server's answer and `clip.updated` (debounced 300 ms) then refetch, and a failure rolls back with a toast.
- **The "USE · MAYBE" chip** is the status view. Its default hides rejected clips, as S10 says, so it is always shown as active. It also offers everything (rejected too), a single status, or not analysed. "Show rejected (n)" switches the same view.
- **Density** is remembered per browser as a convenience. Filters and grouping last for the visit to the project.
- **"Deepen analysis…"** with clips selected collects the moments (segment ids) of up to 50 selected clips and opens S25 on "Current selection". With no selection, S25 opens on days.
- **Hover-scrub** fetches a clip's sample-frame strip (8 frames) the first time the pointer enters its tile, and caches it. It never decodes video.
- **Focus model:** a roving tabindex.
  - Only the focused tile is in the tab order. Focusing a tile makes it the focused clip, and a keyboard move puts DOM focus on the new tile once its row mounts.
  - A focused tile that scrolls out of the virtual window hands focus to the grid itself, so the keys keep working.
  - The first clip takes focus on arrival.
  - The grid has `role="grid"`, with `gridcell` and `aria-selected` on tiles and `rowheader` on group headers.
- **The grid** virtualizes rows: a header row per group, then rows of tiles.
  - **Row heights are fixed,** computed rather than measured.
  - **Columns** start from the density's minimum tile width: 220 px comfortable, 160 px compact. If a viewport's worth of rows plus one overscan row at each edge would mount more than 60 tiles (M2 acceptance 4), the grid uses fewer, larger tiles. So compact tiles grow on very large screens. `layout.gridLayout` is unit-tested across 1280–2560 px widths.
  - **Paging:** every group has its header from the first page on. The next keyset page loads when the first expanded group with clips still to load comes into view (`layout.wantsMoreAt`). Collapsed groups never ask for more, so collapsing every group loads nothing (invariant 13), and a later expanded day still loads past a collapsed one.
  - **The day scrubber** jumps to a loaded day, or filters to that day when it is not loaded yet.
- **More** (the toolbar's last chip) holds the include filter. The tag filter exists in the API but waits for a list of the trip's tags to choose from.
- **The offline overlay** covers files only in the cloud and files missing from an unplugged drive.

## Consequences

- A clip in more than one similarity group appears under only one of them. The inspector's Similar section (ADR 0043) lists all of its look-alikes.
- "Similar N" labels are positional, so the same group can get another number under another filter. Groups have no stable name to show.
- Paging by the similar key, like day paging after a clock correction, can skip or repeat a clip if similarity groups are rebuilt while you scroll. A re-analysis refetches the grid.
- `shot_type` takes the vision schema's values, and an unknown value is a 422.
