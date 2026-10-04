# S1 — First Run

- **Reference:** `docs/ui/reference/` → S1a-FirstRun, S1b-FirstRunAI, S1c-FirstRunModels
- **Milestone:** M3

**Purpose.** Desktop-only welcome flow: choose the AI mode, add a key, download local models.

## Layout

Full-window centered layout with a soft accent glow at the top. Three-dot progress indicator.

**Step 1:** mark, wordmark, tagline "Your trip, told well.", Get started.

**Step 2:** three mode cards (Cloud / Hybrid (Recommended) / Local only); a provider select (default Anthropic; ADR 0003, not in the reference artboard); `SecretField` for the selected provider; a "what's sent" explainer with three columns (Sent / Never sent / Only if you allow).

**Step 3:** two download cards (speech 1.5 GB, image understanding 0.8 GB) and "Continue while downloading".

## States

- Invalid key: inline error under the field.
- Offline: download paused with Retry.
- Local only selected: a list of unavailable features.
- Downloads continue in the background after leaving; progress shows in the activity ring.

## Data & API

- `/providers`, `/secrets/{ref}`, `/secrets/{ref}/validate`, `/models/local`, `/models/local/{name}/download`.

## Keyboard

- Enter = Continue; Esc = Back.

## Acceptance

- After first run, the key exists only in Keychain (verified by a test).
- The chosen provider is saved to `provider_profile` for all cloud capabilities.
- A model download interrupted by quitting resumes on next launch.
