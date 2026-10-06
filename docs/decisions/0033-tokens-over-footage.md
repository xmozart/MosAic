# 0033 — Tokens for content drawn over footage

- Status: accepted (M2 step 2a)
- Deciders: agent (autonomous; no human gate)

## Context

The approved component reference (`DS-Components.dc.html`) draws three kinds of content directly over footage on thumbnails: badges, AI chips, and centred notices such as "360 · analysis only" and "Source offline". They use fixed values:
- `#EDEDEC` for text;
- `rgba(10,11,13,0.62)` behind badges;
- `rgba(10,11,13,0.72)` behind notices.

They also use 11 px and 10 px type for badges, chips, the "AI" tag and `+n` counts.

`tokens.json` had only `scrim` for these elements. The text tokens can't stand in: `text` is near-black in the light theme, so it would be unreadable over a dark frame. Invariant 15 says tokens come only from `tokens.json`, so arbitrary values in components are not allowed.

## Decision

- **New colour tokens.** Add three to `tokens.json`, each with the same value in both themes, because footage isn't themed:
  - `on-media`, `#EDEDEC`: text and icons over footage.
  - `media-chip`, `rgba(10,11,13,0.62)`: backing behind badges and AI chips over footage.
  - `media-overlay`, `rgba(10,11,13,0.72)`: backing behind centred notices.
- **Existing token.** The existing `scrim` token is the label gradient and the scrub progress track.
- **New type styles.** Add two from the reference:
  - `micro`: 11/14, weight 600, for badges and chips on tiles.
  - `tag`: 10/12, weight 600, for the "AI" tag and `+n` counts.
- **Chart shades** (StorageBreakdown) follow S21's order (`info`, `accent`, `use`), then the neutrals `text-muted` and `text-faint`.
  - `user` is never used as a shade: it is reserved for decisions the user made.
  - Neither are the other disposition colours.
  - S21 draws a fourth series in a purple that is not a token; it is replaced by a neutral.

- **Dark tokens over footage.** Everything drawn over footage sits inside a `data-theme="dark"` scope, so the disposition colours, the user badge and the star accent keep the dark values the reference draws, in both themes.
  - The light-theme disposition colours are tuned for light surfaces. Over a dark frame they lose contrast; for example, `use` is #1B7F4F on `media-chip`.
  - The selection outline stays outside that scope and uses the page theme's accent.

## Consequences

- Components contain no hex or rgba values. The only exceptions are the shadow values that DESIGN_TOKENS.md §4 itself specifies, and the Segmented control's inner shadow as drawn.
- `DESIGN_TOKENS.md` lists the new tokens.
