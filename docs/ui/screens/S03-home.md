# S3 — Home

- **Reference:** `docs/ui/reference/` → Main, S3b-HomeEmpty
- **Milestone:** M2

**Purpose.** Launcher for recent projects. MosAic never imports media.

## Layout

Title "Your trips" with a subline. Actions: Open existing project (secondary), Open footage folder (primary, large).

Project cards in a 3-column grid. Each card shows:

- a collage cover (1 large + 2 small best frames)
- name and `PlacementBadge`
- dates · duration · clips · photos
- status dot
- latest edit and last opened

## States

- **Empty (first use):** dashed drop area with a mini collage. Copy: "MosAic works with your files where they are — nothing gets moved or changed."
- **Analyzing:** progress ring overlay on the cover.
- **Missing folder:** card dimmed with "Folder not found". Actions: Reconnect / Remove from list.
- **Card hover:** Open, Reveal in Finder (desktop), Remove from recents.

## Data & API

- `/projects`, `/media/{pid}/frame/{id}` for covers.

## Keyboard

- Arrow keys move between cards; Enter opens.

## Acceptance

- Cards render from the control DB without opening project DBs.
- Missing folders are detected without blocking the list.
