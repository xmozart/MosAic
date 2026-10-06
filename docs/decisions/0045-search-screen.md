# 0045 — The search screen and its results

- Status: accepted (M2 step 7d)
- Deciders: agent (autonomous; no human gate)

## Context

S12's mockup shows the results under the full Library toolbar: search box, filter chips, Group, Density, "Deepen analysis…" and "Create edit". A header reads "n results for …", with All / Visual / Speech and "Try:" suggestions, and each tile has a "matched:" line under it.

There were two problems:
- **The search API takes no filters.** Its results carry neither the day nor the shot type, so the toolbar's chips could not narrow them truthfully.
- **Results used the old decision rule.** They ignored clip decisions (ADR 0042), had no `decided_by`, and called an unanalysed moment USE. A tile could therefore show an AI suggestion styled as the owner's decision, which breaks invariants 10 and 15.

## Decision

- **Results follow ADR 0042.** `search.describe` takes each result's decision from `decisions.for_segments`, with `decided_by` and the AI's own `ai_status`. An unanalysed moment has no status.
  - Each result also carries the clip's name, kind, camera, stars and has-speech, batched over the hits' clips.
  - A tile shows exactly what the Library would show.
- **S12 keeps the search box, the header and the mode.** It leaves out the rest of the Library toolbar: filter chips, Group, Density, "Deepen analysis…" and "Create edit".
  - Narrowing results by day, camera or shot type is the Library's job.
  - Deepening and edit creation start from the Library, where a selection exists. Search has no selection: a click opens the result.
  - The query and mode live in the URL (`?q=&mode=`), so a search can be shared and Back works.
- **The "Try:" chips** are the trip's own most common subjects (`/search/suggestions`, as S12's acceptance asks). The no-results state offers them too.
- **A result is a moment, not a clip.**
  - The tile's length is the moment's.
  - Its "matched:" line is the search's own reasons: "said: …" for speech, "looks like: …" for visual tags.
  - Opening a result opens the clip in S11.
- **Rejected moments are shown.** A search looks for something specific, so hiding rejected results would hide what was asked for. Their chips say REJECT.
- **States**, with the mockup's copy:
  - **No query:** "Search this trip" and the suggestions.
  - **Searching:** skeleton tiles.
  - **No results:** "No clips match “…”" and "Nothing like that in this trip. Try one of these instead:", with the suggestions shown there only.
  - **Analysis incomplete:** the info banner when visual search is unavailable: "While analysis runs, results may improve once it finishes" (the mockup's title and body in one line; the Banner has no title).
  - **Search failed:** "Couldn't search right now", with Try again.
  - A mode other than `visual` or `speech` in the URL means All.
- **Results are batched.** `search.describe` reads the hits' dispositions and clip decisions once and resolves them with `decisions.resolve`, the same rule as `for_segments`. The camera badge comes from `browse.camera_json`, the Library's own helper.

## Consequences

- Filtering search results would need filter parameters on `/search`. That is out of scope for M2.
