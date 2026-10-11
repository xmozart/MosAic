# 0072 — Content categories and weights in retrieval

- Status: accepted (M4 step 5a)
- Deciders: agent (autonomous; no human gate)

## Context

PRODUCT.md §4 weights 22 content categories (people, reactions, landscapes, wildlife, …, timelapse, photos) as Avoid / Less / Neutral / More / Strongly prefer. S14 step 3 shows "the 6 most relevant WeightSliders for this footage". Its acceptance requires that category ordering comes from library tag frequency. The vision observation (vision v1) has no category field. It has a shot type, people, camera motion, subjects and a description. The owner's clip tags (ADR 0042) are free text.

## Decision

- **Categories are derived, deterministically and without an AI call** (`editing/categories.py`), from:
  - **structured fields:**
    - shot type aerial → drone; pov → pov; selfie → selfies and people;
    - wide or establishing with no people → landscapes;
    - people present → people;
    - vehicle camera motion → transport; tracking → action;
  - **speech** → conversations;
  - **source rate** ≥ 100 fps → slow motion;
  - **photo assets** → photos (used from M4 step 6);
  - **words** in the subjects and description. Each is a whole word or its regular plural ("-es" after s, x, z, ch, sh or o; "-ies" after a consonant and y; else "-s"), or a stem marked as such. So "car" never matches "carry" or "cares", and "ski" never matches "skies". Words that name too much ("view", "field") are left out.
  - **the owner's tags** that name a category ("Food", "slow motion").

  A category is a hint for weighting and ordering. It is never shown as a fact or a title (invariant 16).
- **Weights in retrieval.**
  - "Avoid" drops a candidate with that category, unless the owner picked it or a storyboard locked it (or absorbed it into a locked cut) (invariant 10). Locked segments are passed to retrieval (`keep`), so tagging a locked clip with an avoided category never removes the shot. The candidates counted as `avoided` appear in the retrieval counts.
  - "Less", "More" and "Strongly prefer" add −1, +1 or +2 to the candidate's ranking score, which caps the AI's context. A clip counts once: its strongest preference plus its strongest dislike, never a sum over categories.
  - A weight re-ranks clips within a day. It never moves clips between days, because each day keeps its share of the cap. When there are fewer candidates than the cap, only "Avoid" changes what the AI sees until the prompts read the weights (M4 step 5b).
  - Neutral, the default, changes nothing. An edit made without weights retrieves exactly as before and keeps its key: the inputs digest includes a candidate's weight bonus only when it is non-zero.
- **`GET /projects/{pid}/edit-categories`** lists all 22 categories with how many clips have each, most first and in PRODUCT.md's order among equals. A clip counts when any of its segments, or its tags, carry the category. Every analysable clip counts, rejected ones included: it is what the library holds, not what an edit would use. The count streams the library in batches (invariant 13). The wizard shows the first six, and the rest under More categories.
- **The prompts read the weights from M4 step 5b** (planner v3, selector v3). Until then, weights steer which clips the AI sees and in what order.

## Consequences

- The word lists are English and deliberately small. They will miss things; the owner's tags are the way to correct a category. Better categorisation is a vision prompt change for a later milestone, not a reason to call the AI here.
- "More or less of a category" (PRODUCT.md §8, M4 step 4c) becomes a weight change plus a regeneration.
