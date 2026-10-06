# MosAic web UI

React + TypeScript (strict) + Vite, Tailwind 4 and Storybook. Specs: `docs/ui/`.

```sh
npm ci
npm run dev          # http://localhost:5173, API proxied to http://127.0.0.1:8765 (`mosaic serve`)
npm test             # Vitest (also checks tokens.css is current and shipped licenses)
npm run storybook    # every component state, both themes (toolbar)
npm run api          # regenerate src/api/openapi.json + schema.d.ts from the backend
```

- `src/styles/tokens.css` is generated from `docs/ui/tokens.json` by `scripts/prepare.mjs`
  (runs before dev, build and test). Never edit it by hand.
- Fonts (Geist, Geist Mono; SIL OFL 1.1) are bundled from `@fontsource-variable`, never
  fetched at runtime.
- The built app (`dist/`) is served by the API process at `/` (ADR 0032).
