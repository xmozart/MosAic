# 0059 — S1 First run

- Status: accepted (M3 step 3)
- Deciders: agent (autonomous; no human gate)

## Context

S1 (`docs/ui/screens/S01-first-run.md`) is the desktop-only welcome in three steps: welcome; AI mode with the provider's key; on-device model downloads. Its acceptance criteria:
- after the first run, the key exists only in Keychain;
- the chosen provider is saved to `provider_profile` for every cloud capability;
- an interrupted download resumes on the next launch (ADR 0058).

The mockup has three mode cards (Cloud, Hybrid, Local only) and a time estimate on each download.

## Decision

- **When it shows.** A new app setting, `app.first_run_done` (default `false`), records a finished first run. On the desktop, after the token session (ADR 0057), `FirstRunGate` shows S1 until that setting is `true`. The server never shows S1: there, the admin's first visit is S2's setup.
- **Two mode cards, as in S22** (ADR 0053): Hybrid (recommended) and Local only. "Cloud" would send what Hybrid sends, because MosAic never uploads originals. The backend has one switch, `ai.local_only`.
  - **Hybrid** shows a provider select (the cloud providers from `/providers/options`, Anthropic by default; ADR 0003) and the `SecretField`. The key is written once to `/secrets/ai/<provider>` (Keychain on the desktop) and validated. An invalid key shows an inline error, and nothing is kept for a retry.
  - **Local only** lists what is not available.
  - **Continue** writes `ai.local_only`. With Hybrid it also sets the chosen provider for every capability that provider serves, with its preset model, in one `PATCH /providers` (S1 acceptance).
- **Models.** The third step lists the entries the current settings need (`needed` from `/models/local`). It starts each missing one once, reusing a running download. It shows the percentage and the bytes downloaded so far.
  - A download whose job failed (offline) shows "Download paused — check your connection" with Retry, which starts a new job that resumes the `.part` files.
  - "Continue while downloading" finishes the first run. The downloads go on as app jobs in the activity ring.
  - The mockup's time estimate ("About 2 min left") is replaced by bytes so far. The job reports no rate, and a guessed time would mislead on a slow link.
- **Keyboard.** Enter continues; Esc goes back. The key field's own form (Save) never submits the step.

## Consequences

- An existing desktop setup (developers running `mosaic serve`) sees S1 once. Its choices can be changed later in Settings.
- Settings (S22) does not list the local models yet. Larger models (Thorough's `large-v3`) still download on first use through the adapter fallback. A models section in S22 is a follow-up.
