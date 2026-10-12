# 0079 — Title cards: the owner's words and the capture dates, drawn in Geist

- Status: accepted (M4 step 9b)
- Deciders: agent (autonomous; no human gate)

## Context

M4 asks for "minimal title cards (opening, day cards, closing) in one modern style" and "titles only from context". Invariant 16 says titles may name places or people only when they come from the trip context, metadata or explicit user input. The fonts must be bundled (Geist, SIL OFL), never fetched (invariant 15). ADR 0066 dips to black around title cards in "Mostly cuts".

The planner writes a working title for each edit. It is told never to invent names, but nothing checks that it obeyed.

## Decision

- **What a card says** comes only from the trip context and capture metadata, never from the AI:
  - **Opening** (3 s): the trip's name as the owner typed it, over the dates the edit's footage was shot ("12 – 18 June 2026"); without a name, the dates alone; with neither, no card.
  - **Day cards** (2 s): "Day N" over the itinerary's place for that date (when the owner gave one) and the date ("Reykjavík · Saturday 13 June"). Only when the edit follows the order things happened (`strict` or `mostly`), covers at least two days and runs at least a minute. Placed before the first shot of each day, and only when the day moves forward ("mostly" may step back in time).
  - **Closing** (3 s): the trip's name, when there is one.
  - The planner's working title stays in the timeline's metadata. It is never drawn.
- **Length.** Cards take at most 15 % of the edit. When day cards would pass that, none are made (one alone tells nothing). Edits under 20 s get no cards. Card frames are taken from the footage: the solver aims for the target less the cards (reserved from the selection's days, settled once the edit's days are known), so the edit still lands on its length.
- **Style.** Centred text on a near-black ground: the title in Geist SemiBold (7.5 % of the short side; it shrinks to fit, then wraps onto two lines), the subtitle in Geist Regular, grey. Drawn by Pillow at the render's size, in any aspect.
- **Fonts.** The latin, latin-ext, cyrillic, cyrillic-ext and vietnamese Geist subsets that the UI already bundles are copied into `backend/mosaic/media/fonts/` with the OFL. Each character is drawn with the subset that covers it. A line with a character no subset covers (Hebrew, Arabic, CJK...) is left out, and a card with no line is not made: a box of missing glyphs is never drawn. Right-to-left and CJK text need fonts and shaping we do not bundle yet.
- **Timeline.** A card is an event of `kind: "title"` with `title: {card, title, subtitle, day}`, `duration`, no asset or segment, silent audio, and a dip in and out of half a second (none in "Minimal"). The card carries both halves of ADR 0066's "dip around title cards": the shot before it cuts to the card's first, black frame, and the card fades out to black before the next shot. Cards sit between shots, so no dissolve, dip or J/L cut is made at a card's boundary. The critic times the footage alone; its findings are moved past the cards before them, and the edit's target and total include the cards.
- **Rendering.** A card renders like a still (ADR 0075) from its drawn image, without motion, with its fades. Its chunk key is its text, frames and fades, the card style (`title/1`), a digest of the bundled font files, the still pipeline's version and the profile. Month and weekday names are English tables, not the process locale, so the text never depends on where the server runs.
- **Consumers.** Everything that reads a clip from an event skips cards (`titles.shot_events`): the selection report, the edit's cover and facts, locks, evaluation and the render's shape. The preview's beat strip shows a card as "Title".
- `EDIT_VERSION` is `edit/4`: edits now carry cards.

## Consequences

- Every edit with a known date or a trip name opens on a card. With "Mostly cuts", the default, it fades in from black.
- An owner who types the trip name in a script we cannot draw gets a card with the dates only. Adding Hebrew (with bidi shaping) is a later change that needs a font and `fribidi`/raqm.
- Cards are not editable on the storyboard yet; their text changes with the trip context, which is part of the edit's key.
