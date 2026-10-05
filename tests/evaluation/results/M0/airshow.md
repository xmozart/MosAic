# Airshow — M0 rubric

Scored by the owner at gate G6 (EVALUATION.md §3). Score each 1–5; add a sentence where useful.
Metrics, cost, model and prompt versions are in the matching `.json` file.

| Criterion | Score (1–5) | Notes |
|---|---|---|
| Opening | 4| Good starting/opening scene selcted |
| Story flow | 2|  clips are too short and interup the important parts where planes are seen|
| Variety | 4|too many cuts |
| Pacing | 3| maybe less cuts, and a bit longer clips would be better|
| Cut quality | 4| no comments on the cuts themselves |
| Audio | 5| |
| Ending | 4| good|
| Would I share this? | 2| not as is|

Expectations: review `tests/evaluation/corpus/<trip>/expectations.yaml`, edit it, and set
`draft: false` to make its must-include and must-exclude metrics count.

## Owner review (G6, 2026-10-05)

"Overall the results are not bad. The airshow could absolutely use a bit of context, so more
footage of the planes themselves could be selected. For example, I am missing many planes and
the main demo of the F-35, but too many clips of the crowd around the show. So this one needs
more work. Context is probably the key here."

Agent analysis: vision named aircraft in only 31 of 485 segments. In 392 px contact-sheet
tiles from 4K footage, a fast jet is a few pixels ("blue sky with a tiny dark speck"), so many
aircraft passes were rated as empty sky. M1 focus: trip context in planner/selector/summaries,
and an L3 (Thorough) full-resolution, context-aware review of sky/aircraft candidates.
