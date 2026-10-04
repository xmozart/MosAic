# MosAic UI Specification

The approved designs are the visual reference. These documents are the behavioral authority.

| Source | Link / path | Authority |
|---|---|---|
| App UI canvas (approved) | https://claude.ai/artifact/K5A2TuoKdXjcnoSrFxXNSc | Visual reference (layout, hierarchy, copy) |
| Design system (approved) | https://claude.ai/artifact/2tiJkvRfQE5rWvdsQ3sb55 | Tokens, brand rules, logo |
| `docs/ui/reference/*.dc.html` | Exported source of every artboard | Readable markup with inline styles; use it to match spacing, sizes and copy exactly |
| `docs/ui/tokens.json` | Token values (dark + light) | **Authoritative** for colors, type, spacing, radius |
| `docs/ui/DESIGN_TOKENS.md` | How tokens map to Tailwind/CSS | Authoritative |
| `docs/ui/COMPONENTS.md` | Shared components, props, states | Authoritative |
| `docs/ui/API_MAP.md` | Endpoints and events the screens need | Authoritative |
| `docs/ui/screens/S##-*.md` | One spec per screen | Authoritative for behavior and states |

## Rules for Claude Code

1. **Build from components.** Build screens from `COMPONENTS.md` components on shadcn/ui primitives. The reference files are inline-styled mockups; never paste their markup into the product.
2. **Thumbnails in the references are stand-ins.** The colored gradients in the reference files stand in for footage frames. The product shows real frames from `/api/media/...`.
3. **Resolving conflicts.** If a reference file and a screen spec disagree, the spec wins. Note the difference in an ADR.
4. **States.** Every state listed in a screen spec must exist in the product and have a Storybook story. Storybook is part of M2.
5. **Copy.** Copy in the references is final unless a spec says otherwise. Voice rules are in `docs/ui/brand/VOICE.md`.
6. **Fonts.** Geist and Geist Mono (SIL OFL 1.1) are **bundled with the app**, not loaded from Google Fonts, so desktop works offline. Add both to `LICENSES.md`.
7. **Themes.** Dark is the default; light is complete. Theme follows the OS until the user chooses.
8. **Viewport.** The primary viewport is 1440×900 and the minimum is 1280×800. Layouts stretch fluidly above 1440. Mobile is out of scope.

## Screen index

| ID | Screen | Reference artboard(s) | Milestone |
|---|---|---|---|
| S0 | App shell, global dialogs, command palette | every screen, `S0-Dialogs` | M2 |
| S1 | First run (desktop) | `S1a/S1b/S1c-FirstRun*` | M3 |
| S2 | Sign in (server) | `S2-SignIn` | M2 |
| S3 | Home | `Main`, `S3b-HomeEmpty` | M2 |
| S4 | Open folder | `S4-FolderBrowser`, `S4b-OpenConfirm` | M2 |
| S5 | Inventory | `S5-Inventory` | M2 |
| S6 | Clock check | `S6-ClockCheck` | M2 |
| S7 | Trip context | `S7-TripContext` | M2 |
| S8 | Analysis setup | `S8-AnalysisSetup` | M2 |
| S9 | Analysis progress | `S9-AnalysisProgress`, `S9b-ProgressStates` | M2 |
| S10 | Library / review | `S10`, `S10b`, `S10c`, `S10d` | M2 |
| S11 | Clip detail | `S11-ClipDetail`, `S11b-ClipVariants` | M2 |
| S12 | Search | `S12-Search` | M2 |
| S13 | Edits | `S13-Edits` | M2 (basic) / M4 |
| S14 | Create edit wizard | `S14`, `S14b`, `S14c` | M2 (basic) / M4 |
| S15 | Creating edit | `S15-Creating` | M4 |
| S16 | Storyboard | `S16-Storyboard` | M4 |
| S17 | Preview & findings | `S17-Preview` | M2 (player + report) / M4 |
| S18 | Versions & compare | `S18-Versions` | M4 |
| S19 | Export | `S19-Export` | M4 |
| S20 | Exports queue | `S20-Exports` | M2 |
| S21 | Project settings | `S21-ProjectSettings` | M2 |
| S22 | App settings | `S22-AppSettings`, `S22b-SettingsMore` | M2 |
| S23 | Diagnostics | `S23-Diagnostics` | M2 |
| S24 | Help me label | `S24-HelpLabel` | M4 |
| S25 | Deepen analysis | `S25-Deepen` | M2 |
| S26 | Timeline editor | `S26-Timeline` | M8 (direction only) |
| DS | Foundations, components, logo | `DS-*` | M2 |

The canvas is a working prototype. In the canvas, press Play on Home to follow the main journey.
