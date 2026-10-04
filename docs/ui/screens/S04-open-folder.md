# S4 — Open Folder

- **Reference:** `docs/ui/reference/` → S4-FolderBrowser, S4b-OpenConfirm
- **Milestone:** M2

**Purpose.** Pick a folder, then confirm project creation and storage placement.

## Layout

**Server:** dialog showing a media-root pill and breadcrumbs. Each folder row shows a folder icon, name, video/photo counts and a "MosAic project" badge when one exists. Primary action: Open this folder.

**Desktop:** native picker, then the confirm dialog.

**Confirm dialog (620 px):**

- path (mono) with the quick-scan summary
- project name field
- three placement explanations; the one that applies is highlighted
- green promise row: **"Original footage stays where it is and will not be modified."**
- Create project

## States

- Folder already a project: skip confirmation and open it.
- Read-only or cloud-synced folder: the matching placement is highlighted.
- Empty folder (no media found): "No videos or photos here" with Choose another.

## Data & API

- `/fs/browse`, `/projects/preview`, `POST /projects`.

## Keyboard

- ↑/↓ select, → enter folder, ← go up, Enter open.

## Acceptance

- `/projects/preview` performs no writes (asserted by a test).
- Paths outside media roots are never listed.
