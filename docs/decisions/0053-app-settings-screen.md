# 0053 — The app settings screen (S22)

- Status: accepted (M2 step 9c)
- Deciders: agent (autonomous; no human gate)

## Context

S22's mockups (S22 and S22b) show a group nav with Appearance, Analysis defaults, Editing defaults, Story library, Music, Export defaults, AI providers, Processing & hardware, Media roots (Admin) and About. They draw the AI providers group in full:
- an API key card;
- a "models by task" table showing provider, "Auto · economy", mode and source;
- privacy mode cards for Cloud, Hybrid and Local only;
- a "What leaves this computer" card.

S22b adds hardware, workers, a battery toggle, a processing device, a default cost limit and media roots.

The spec requires every row to show its effective value and source, and Reset returns a value to the lower scope. Its states are key missing, key invalid and local-only.

Several of these did not fit M2 as it stood:
- Editing defaults, Story library, Music and Export defaults belong to M4's wizard and export work.
- The backend has one privacy switch (`ai.local_only`), not three modes. MosAic never uploads originals, so "Cloud" and "Hybrid" would send the same things.
- Nothing listed the providers, models and presets, and nothing reset one task's choice.
- There is no battery-aware scheduling and no choice of processing device.

## Decision

- **Sections:** Appearance, Analysis defaults, AI providers, Processing & hardware, Media roots (server only) and About.
  - Editing defaults, Story library, Music and Export defaults arrive with M4. Until then they are not listed, so the nav has no dead entries.
  - When a trip has been opened, a card at the top links to its project settings (ADR 0052).
- **Appearance.** Theme is System, Dark or Light. The choice is a per-viewer convenience kept in this browser, as before. Reset returns to System.
- **Analysis defaults.** Two user settings with source and Reset: the analysis mode, and the AI cost limit per run (`ai.budget.per_job_usd`).
- **AI providers.**
  - **Key cards.** One `SecretField` per cloud provider that some task uses.
    - It shows where the key lives: system keychain, encrypted on this server, environment or Docker secret.
    - It shows "Connected · ••••last4", or "Key was rejected" after Validate.
    - A deployment key says that a key added here is used instead (ADR 0036).
    - Saving a key validates it straight away, except in Local only, where nothing is sent, not even a check.
    - A failed check (network, server) is not a verdict: it shows "Couldn't check the key", never "Key was rejected".
    - **Remove key** (`DELETE /secrets/{ref}`) is offered for a key the user entered. The deployment's key, if any, is then used again; this is the key card's Reset to the lower scope (ADR 0036).
    - With no key, the card says which tasks can't run.
  - **Adding a provider** means choosing it for a task in the table, using `GET /providers/options`. Changing a task's provider uses that provider's preset model, and a cloud provider's key card then appears.
  - **The models-by-task table** has one row for each of the eight tasks, in plain words.
    - Each row has a provider select, limited to the providers that can serve the task, and a model. The model is a fixed list for local providers and a suggested list otherwise.
    - It also shows the mode (Cloud, Installed app, On this computer), the source (default, your preference, your provider choice) and Reset. Reset is `PATCH /providers {task: null}`, which removes the user's row.
    - Rows show the model ids themselves (`claude-haiku-4-5`), not the mockup's "Auto · economy". An "Auto" tier would be a new feature of the provider layer.
  - **Local only** disables the provider and model controls on cloud and installed-app rows, and marks them "Paused · local only", as the spec's "cloud rows disabled" asks.
  - **Error toasts** use the server's message only when it is plain text without CLI hints. Otherwise they use product copy.
  - **Layout differences from the mockup:**
    - The table has a visually hidden header row (Task, Provider, Model, Runs, Reset).
    - "From:" sits under each task's name rather than in its own column.
    - A current provider the options don't offer is shown, disabled.
    - A worker count set elsewhere shows as "Custom: n".
    - The Media roots entry carries the mockup's "Admin" tag.
  - **Privacy mode** has two cards. **Hybrid** (`ai.local_only` off) means processing stays here and the AI sees selected frames and text. **Local only** pauses every cloud and installed-app task, shown on their rows.
    - The mockup's third card, Cloud, is left out: it would send exactly what Hybrid sends.
  - **"What leaves this computer"** is built from the settings:
    - contact sheets and transcripts are sent in Hybrid;
    - originals and API keys are never sent;
    - GPS is never sent: off, or "on by default for new trips", which no analysis step uses yet (ADR 0041).
- **Processing & hardware.**
  - The hardware line shows the CPU, threads, memory and hardware encoders.
  - Background workers are Auto, 2, 4 or 8 (`workers.cpu`, with source and Reset).
  - The battery toggle and the processing-device choice are left out until the scheduler supports them.
- **Media roots** (server only, `/admin/media-roots`): list, add and remove. Roots that come from the deployment (`MOSAIC_MEDIA_ROOTS`) cannot be removed here.
- **About** shows the MosAic version, the FFmpeg version and its licence, and a privacy line.

## Consequences

- `GET /providers/options` and `PATCH /providers {task: null}` are new, with tests.
- The STATUS item "S22 app (five config scopes…)" is satisfied for M2. App settings use the user and default scopes, S21 uses the project scope, and the server's deployment and admin scopes show as sources (keys, media roots). The installation scope has no app setting yet.
