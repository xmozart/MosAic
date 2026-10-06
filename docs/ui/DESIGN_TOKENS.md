# Design Tokens

Source of truth: `docs/ui/tokens.json`. The values below are copied from it. If they ever differ, `tokens.json` wins.

## 1. CSS variables

Generate `frontend/src/styles/tokens.css` from `tokens.json` with a build script. Do not hand-edit it.

```css
:root, [data-theme="dark"] {
  --bg: #0E0F11; --surface-1: #16181B; --surface-2: #1E2125; --surface-3: #272B30;
  --border: #2E3238; --text: #EDEDEC; --text-muted: #A1A4A8; --text-faint: #7C8087;
  --accent: #F2A541; --accent-fg: #1A1206; --accent-soft: #3A2A12;
  --use: #4CC38A; --maybe: #E6C35C; --reject: #F0575C; --user: #7AA2F7; --info: #6CB6D9;
  --scrim: rgba(0,0,0,0.55);
  --on-media: #EDEDEC; --media-chip: rgba(10,11,13,0.62); --media-overlay: rgba(10,11,13,0.72);
  --cam-1: #F2A541; --cam-2: #6CB6D9; --cam-3: #B48CF0; --cam-4: #4CC38A; --cam-5: #E6C35C; --cam-6: #E07A5F;
}
[data-theme="light"] {
  --bg: #F7F6F3; --surface-1: #FFFFFF; --surface-2: #F0EFEB; --surface-3: #E6E4DF;
  --border: #DAD7D0; --text: #16181B; --text-muted: #5C6066; --text-faint: #74787E;
  --accent: #A86208; --accent-fg: #FFFFFF; --accent-soft: #F6E6CC;
  --use: #1B7F4F; --maybe: #8A6B0A; --reject: #C22A2F; --user: #3558C9; --info: #1F6F95;
  --scrim: rgba(0,0,0,0.45);
  --on-media: #EDEDEC; --media-chip: rgba(10,11,13,0.62); --media-overlay: rgba(10,11,13,0.72);
  --cam-1: #A86208; --cam-2: #1F6F95; --cam-3: #7246C2; --cam-4: #1B7F4F; --cam-5: #8A6B0A; --cam-6: #B4492F;
}
```

## 2. Tailwind mapping

Expose every token as a Tailwind color (for example `bg-surface-1`, `text-text-muted`, `border-border`, `bg-accent`, `text-use`). With Tailwind 4 this is the generated `@theme` block in `tokens.css`, not a `tailwind.config` file (ADR 0032).

Map the shadcn/ui CSS variables onto these tokens:

| shadcn var | MosAic token |
|---|---|
| `background` | `bg` |
| `card` | `surface-1` |
| `popover` | `surface-2` |
| `primary` | `accent` |
| `primary-foreground` | `accent-fg` |
| `muted` | `surface-2` |
| `muted-foreground` | `text-muted` |
| `border` | `border` |
| `input` | `border` |
| `ring` | `accent` |
| `destructive` | `reject` |

## 3. Type

| Style | Size / line height | Weight | Family |
|---|---|---|---|
| display | 32/38 | 600 | Geist |
| title | 24/30 | 600 | Geist |
| heading | 18/24 | 600 | Geist |
| subhead | 15/22 | 500 | Geist |
| body (base) | 14/20 | 400 | Geist |
| small | 13/18 | 400 | Geist |
| caption | 12/16 | 500 | Geist |
| micro | 11/14 | 600 | Geist (badges and chips on tiles) |
| tag | 10/12 | 600 | Geist (the "AI" tag, `+n` counts) |
| timecode | 13/18 | 500 | Geist Mono, `font-variant-numeric: tabular-nums` |
| timecode-sm | 11/14 | 500 | Geist Mono, tabular |

- Letter-spacing −0.01em on headings and −0.02em on the wordmark.
- Every timecode, duration, cost, size and filename uses Geist Mono.

**Over footage** (ADR 0033): text and icons use `on-media`, badges `media-chip`, centred notices `media-overlay`, label gradients `scrim`. These do not change with the theme, because footage does not.

**Camera series** (ADR 0040): `cam-1` … `cam-6` tell cameras apart in charts (S5 trip timeline and legend, S21 devices), in the order the screen lists the cameras; a seventh camera repeats `cam-1`. They are never used for dispositions or user decisions, and a chart always pairs them with the camera's name (legend or label).

## 4. Spacing, radius, motion

**Spacing:** 4, 8, 12, 16, 24, 32, 48 px (`space-1/2/3/4/6/8/12`).

**Radius:**

| Token | Value | Use |
|---|---|---|
| `sm` | 6 | Chips inside tiles |
| `md` | 10 | Tiles, inputs, buttons |
| `lg` | 14 | Cards, panels |
| — | 16 | Dialogs (as drawn) |
| `full` | 999 | Pills |

**Shadows** are used only on popovers, dialogs, toasts, the bulk action bar and drag previews. Use `0 24px 64px rgba(0,0,0,.5)` for dialogs and `0 12px 32px rgba(0,0,0,.4)` for toasts.

**Motion:**
- 150 ms ease-out for state changes and 250 ms for sheets and dialogs.
- Thumbnail hover-scrub is instant.
- With `prefers-reduced-motion`, disable the activity-ring pulse and shimmer animations.

## 5. Signature rules (enforced in code review)

- **AI vs. you.** An AI-set disposition is an outlined chip with an "AI" tag. A user-set disposition is a filled chip with a `user`-blue person badge. Locks and Always/Never include always use `user` blue.
- **Dispositions** are never shown by color alone. USE ✓, MAYBE ◐ and REJECT ✕ each pair color with an icon and the word.
- **Accent** is used for the primary action, the selection outline (2 px, 2 px offset), the playhead, the active nav item and progress. Aim for one primary button per view.
- **Light theme** uses the same token names with no separate component styling.
