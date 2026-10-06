# 0032 — Web UI foundation

- Status: accepted (M2 step 1)
- Deciders: agent (autonomous; no human gate)

## Context

M2 starts with the design foundation: tokens generated from `docs/ui/tokens.json`, a Tailwind and shadcn mapping, bundled Geist fonts, dark and light themes, Storybook, and a client generated from the API's OpenAPI schema (acceptance 9). CLAUDE.md fixes React, TypeScript (strict), Vite, Tailwind, shadcn/ui, Zustand, TanStack Query and Vitest. Several smaller choices are left open.

## Decision

- **Package manager:** npm, with `package-lock.json` and `npm ci` in `make ci`. It is the only Node tool on the machine and in the default CI images.
- **TypeScript 5.9**, not the scaffold's 6.0: openapi-typescript 7 and most tooling declare TypeScript 5 as their peer.
- **Tailwind 4, configured in CSS.** Tailwind 4 has no `tailwind.config` by default. `DESIGN_TOKENS.md` §2 asks for "every token as a Tailwind color through `tailwind.config`", and the generated `tokens.css` does the same through `@theme`:
  - Each token is a utility. Colour token names are kept 1:1, so the classes are `bg-surface-1`, `text-text-muted`, `border-border`, `bg-accent` and `text-use`. The doc's `text-muted` example is spelled `text-text-muted`, because `muted` is the shadcn alias (below).
  - The shadcn names are aliases: `background`, `card`, `popover`, `primary`, `muted`, `muted-foreground`, `input`, `ring`, `destructive`.
  - shadcn's own hover "accent" is not mapped: MosAic's `accent` is the amber token.
  - The type styles are utilities (`text-display` … `text-timecode-sm`) carrying their size, line height and weight. `mono` is the tabular Geist Mono utility.
  - The spacing scale matches Tailwind's 4 px steps (`p-1`, `p-2`, `p-3`, `p-4`, `p-6`, `p-8` and `p-12` are 4–48 px), so it needs no override.
- **Generated tokens.** `scripts/prepare.mjs` writes `src/styles/tokens.css` before dev, build and test.
  - The file is committed. `npm test` runs `prepare --check` first and fails if it is out of date.
  - Themes: `data-theme="dark|light"` on `<html>`. With no attribute, the theme follows the OS, and dark is the default.
  - The choice is stored in browser storage (a per-viewer convenience) and applied before the first paint.
- **Fonts.** The fonts come from `@fontsource-variable/geist` and `@fontsource-variable/geist-mono` (OFL-1.1, no dependencies). The prepare script copies their files and writes `@font-face` rules under the token family names (`"Geist"`, `"Geist Mono"`) with every unicode subset kept.
  - Not the `geist` npm package: it declares Next.js as a peer dependency, which npm installs, and that brings in sharp with LGPL libvips.
  - `src/test/licenses.test.ts` walks the shipped dependency tree. It fails on any license that is not allowed and on any shipped package missing from `LICENSES.md` (matched by whole name).
  - 0BSD (`tslib`) is accepted as a form of BSD, which CLAUDE.md allows: it is BSD without the attribution clause, equivalent to public domain.
- **Libraries:** react-router 8, openapi-fetch with openapi-typescript types, and oxlint (the scaffold's linter) over ESLint.
- **Storybook 10** (react-vite), with a theme toolbar and the story decorator setting `data-theme`.
- **OpenAPI.** `python -m mosaic.app.openapi_export` writes the schema without starting any services.
  - `npm run api` regenerates `src/api/openapi.json` and `schema.d.ts`.
  - A backend unit test fails when the committed document differs from the API.
- **Serving.** The API process serves the built UI.
  - `frontend/dist` (or `$MOSAIC_UI_DIR`) is served at `/`. Assets come from `/assets`, and every other non-API path returns `index.html` for client-side routes.
  - `/api/*` never falls through to the UI, and no file outside the UI folder is served.
  - One process serves both API and UI, for desktop and Docker alike (invariant 12).

## Consequences

- `make ci` gains a `frontend` target: `npm ci`, tests, typecheck, lint, build and the Storybook build.
- The GitHub workflow adds Node 24, and its timeout goes to 120 minutes because of the 40-hour test (ADR 0031).
- shadcn components are added as needed and restyled with MosAic tokens. Their default hover "accent" classes must be replaced when a component is added.
