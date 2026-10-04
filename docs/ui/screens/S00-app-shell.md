# S0 — App Shell

- **Reference:** `docs/ui/reference/` → every artboard; S0-Dialogs
- **Milestone:** M2

**Purpose.** Persistent frame for every project screen, plus global dialogs and the command palette.

## Layout

`AppRail` (72 px) on the left, `ProjectHeader` (56 px) at the top, content fills the rest. An optional right inspector is 360–420 px.

Home and Settings use a reduced header: the wordmark or page title, with no project status.

Background activity ring in the rail. Clicking it opens `ActivityPopover`.

## States

- **Project open elsewhere:** shows holder host and time. Actions: Open read-only / Take over (destructive style) / Cancel.
- **Cost ceiling reached:** has a new-limit field. Actions: Raise limit / Keep paused.
- **Files moved:** "n clips aren't where they used to be; found m in <path>". Actions: Relink m / Choose folder… / Skip.
- **Unsaved draft changes:** summarizes the changes. Actions: Save as vN / Discard / Cancel.
- **Read-only mode:** a banner under the header; all write controls are disabled with a tooltip explaining why.
- **Lost lease** (`lock.lost` event): a blocking dialog that offers read-only mode.

## Data & API

- `/system/info`, `/jobs?active=1`, SSE `/events`, `/projects/{pid}/open`.

## Keyboard

- ⌘K opens the command palette; Esc closes dialogs and popovers; / focuses search on Library screens.

## Acceptance

- The activity ring reflects every running job within 1 s of an SSE event.
- All four dialogs exist as Storybook stories in both themes.
