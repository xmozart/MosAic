# 0076 — Subject focus from saliency, for crops and still motion

- Status: accepted (M4 step 7)
- Deciders: agent (autonomous; no human gate)

## Context

M4 asks for non-native aspect ratios to use "center crop, or subject crop from vision observations with smoothing. This is not full smart reframing." It also asks for subject-aware pan/zoom for stills.

The vision observation (v1) has no subject position, and adding one would mean re-running vision, a paid AI call, over every library. Face recognition and named-people identification must not be built (CLAUDE.md). The analysis already stores a few 640 px sample frames per shot.

## Decision

- **A subject's position comes from saliency, not from the AI and not from faces.**
  - `media/saliency.py` computes the spectral residual saliency (Hou & Zhang, 2007) of a small grey copy of a frame, with numpy and SciPy.
  - The focus point is the saliency-weighted centroid, squared towards the peaks, in thousandths of the frame.
  - It finds what stands out (contrast, edges, colour), never who.
- **A new L1 stage, `library.focus`**, runs after `segments` for videos and after `photo_segment` for photos.
  - It averages the maps of up to four kept sample frames from each segment's usable range (a photo's one sample), so each segment has one steady point. This is the "smoothing": a crop never wanders within a shot.
  - It stores the point on the segment (`focus_x`, `focus_y`; migration `d9f2b6c41e08`).
  - It is keyed by the asset's segments and samples, so re-segmenting recomputes it.
  - Segments analysed before this stage have no point until the next analysis run, which runs only this new stage, with no AI. Until then they fall back to the centre.
- **Edits carry the point** in each event's `transform.focus` (thousandths, integers).
- **Rendering a crop to another shape** (ADR 0046's crop framing) centres the window on the focus, kept inside the picture. Without a focus it crops the centre. Fit framing (bars) ignores the point.
- **A still's push-in ends on its subject** (ADR 0075): the 85 % rectangle is centred on the focus, kept inside the frame.
- The chunk key already covers the event's transform. So a clip with a focus renders afresh, and an unchanged one is reused.

## Consequences

- A 9:16 reel from landscape footage keeps the subject in frame rather than the middle of the frame. This is a static crop per event, not tracking. Smart reframing (a moving crop) is M8.
- A still's focus is in thousandths of the photo, while its motion rectangles are thousandths of the canvas. These differ when the canvas crops a photo or sets it on a blurred fill (ADR 0075). With only 15 % of room to move, both usually clamp alike, so this is an accepted approximation; mapping through the canvas geometry is polish for later.
- An unreadable sample frame is skipped. A segment with none left keeps no focus (the centre), and the stage never fails for it (invariant 14).
- Saliency can pick a bright sky over a dark subject. The centroid stays inside the frame, and a wrong pick crops no worse than the centre would.
