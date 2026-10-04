# S22 — App Settings

- **Reference:** `docs/ui/reference/` → S22-AppSettings, S22b-SettingsMore
- **Milestone:** M2

**Purpose.** Application preferences, AI providers, processing, media roots.

## Layout

Left group nav. **AI providers** contains:

- one API key card (`SecretField`) per configured provider, plus Add provider (ADR 0003)
- a models-by-task table (task, provider, model, mode, "From:" source) where provider and model are editable per task
- privacy mode cards
- a "What leaves this computer" card
**Processing:** hardware card, workers, battery toggle, device, default cost limit (with source and Reset).

**Media roots** (admin): list with type tags, Add or Remove.

## States

- Key missing.
- Key invalid.
- Local-only (cloud rows disabled).

## Data & API

- `/settings`, `/providers`, `/secrets/*`, `/system/info`, `/admin/media-roots`.

## Acceptance

- Every row shows its effective value and source; Reset returns it to the lower scope.
