# 0046 — Destination: aspect and resolution are render settings

- Status: accepted (M2 step 8a)
- Deciders: agent (autonomous; no human gate)

## Context

S14 step 1 asks for the destination: an aspect (16:9, 9:16, 4:5, 1:1, 2.39:1) and, under More options, a resolution (PRODUCT.md §4 Destination). Until now every render was 16:9: previews at 720p and finals at 1080p.

Three questions needed an answer:
- **Does the aspect change which shots are picked?** S13's "Vertical version of the reel" chip makes a 9:16 copy of an existing edit. If the aspect were part of the edit's key (invariant 9), the copy would re-plan and pay for new planner and selector calls, and it could pick different shots.
- **How does a clip fill a frame of another shape?** PRODUCT.md §4 says "Non-native aspect ratios use a center/subject crop in v1". A portrait phone clip inside a landscape edit of landscape footage is a different case: the owner did not ask for a different shape, and a centre crop would keep a third of the picture.
- **What about "native", "custom" and "source"?** These are among PRODUCT.md's presets, but S14's mockup offers only the five aspects plus "Native".

## Decision

- **Aspect and resolution are render-only.**
  - `EditRequest` gains `aspect` (default `16:9`) and `resolution` (default `1080p`).
  - Both are listed in `RENDER_ONLY` and excluded from the edit key (`EditRequest.key_dump`). A vertical copy therefore reuses the plan, and through the AI cache it makes no AI call.
  - The version row still records the full request, so a render knows its shape.
- **The render profile** takes its size from the request:
  - The short side is 720 px for previews and 720 / 1080 / 1440 / 2160 px for finals. Final bitrates are 8 / 14 / 24 / 45 Mbit/s.
  - The long side follows the aspect, rounded to even: 9:16 at 1080 is 1080 × 1920.
  - The long side is capped at 4096 px, and the short side shrinks to keep the shape. 2.39:1 at 4K is therefore 4096 × 1714. Every H.264 encoder MosAic uses accepts that size: it is within level 5.2 and NVENC's 4096 px width. Uncapped, it would be 5162 × 2160.
- **Framing, per clip:**
  - **The profile's `fill`.** `create_render` works out the edit's native shape: the display shape that covers most of its running time (`dominant_shape`). If the chosen aspect is more than 25 % away from it, the profile's `fill` is `crop`, and every clip fills the frame with a centre crop. This covers a reel made from landscape footage, as PRODUCT.md asks.
  - **Otherwise (`auto`):**
    - A clip within 25 % of the frame's shape is cropped. A 16:10 clip in a 16:9 frame loses its slim edges.
    - A clip further off is fitted whole, with bars. A portrait clip in a landscape edit of landscape footage stays whole.
    - A clip with no known size is fitted.
  - Subject-aware reframing remains a later milestone.
- **`fill` is part of the profile JSON,** so it enters the chunk key. `RENDER_VERSION` goes to `render/3`, and chunks rendered before this change are re-made once.
- **"Native", "custom" and "source" wait.**
  - M2 offers the five aspects. S14 step 1 shows "Native" disabled, with the tooltip "Coming soon".
  - Resolution offers 720p / 1080p / 1440p / 4K. "Source" is left out.
  - Frame rate stays the existing `fps` field.

## Consequences

- Changing an edit's shape costs a render, never an AI call. The integration test `test_a_vertical_edit_renders_vertical_with_the_same_plan` checks this: the timeline is identical, there are no new AI calls, and the preview is 720 × 1280 and frame-exact.
- An edit made only of portrait clips has a native shape of 9:16, so a 16:9 render of it crops every clip. That follows PRODUCT.md's rule for non-native output.
- An edit whose clips mix shapes, such as some 4:3 clips in a 16:9 trip, crops the 4:3 clips only if they cover most of the running time. Otherwise they are fitted with thin bars.
- **For M4 (editing an existing edit's request):** a render reads its shape from the version's request. Because the shape is not in the key, regenerating after a shape-only change makes no new version. A change of shape must therefore write the version's request, or render with the new shape, instead of regenerating.
