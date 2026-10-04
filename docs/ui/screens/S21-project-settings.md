# S21 — Project Settings

- **Reference:** `docs/ui/reference/` → S21-ProjectSettings
- **Milestone:** M2

**Purpose.** Project-level settings, storage and removal.

## Layout

Left section nav (General, Analysis, Devices, Trip context, Storage, Danger zone).

**Storage:** total, stacked bar, legend with Regenerable/Kept tags, Clear regenerable files.

**Danger zone:** Remove MosAic data from this folder.

## States

- Clear-cache confirmation states the space freed and lists what is kept.
- Removal confirmation requires typing the project name.

## Data & API

- `/settings`, `/storage`, `/storage/clear-cache`, `DELETE /workspace`, `/devices`.

## Acceptance

- Clear cache never deletes durable data (`ARCHITECTURE.md` and the M1 tests).
