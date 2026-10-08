# 0052 — The project settings screen (S21) and renaming a project

- Status: accepted (M2 step 9b)
- Deciders: agent (autonomous; no human gate)

## Context

S21's mockup shows a section nav (General, Analysis, Devices, Trip context, Storage, Danger zone) and draws the Storage section in full. The other sections come from the spec's data list: `/settings`, `/storage`, `/storage/clear-cache`, `DELETE /workspace`, `/devices`.

Three things were open:
- the rail's Settings item opens the app settings (S22), and there was no route to S21;
- renaming a project had no endpoint, although the header's inline rename was built in 5b (a STATUS carry-forward);
- S8 already edits the analysis parameters.

## Decision

- **Route and reach.**
  - S21 is `/p/:pid/settings`.
  - It is reached from the command palette ("Project settings") and from S22's nav when a project is open (step 9c).
  - The rail's Settings item stays the app's settings.
- **Layout.** S21 is one scrolling column, at most 720 px wide, beside the 220 px `SectionNav`. The nav scrolls to a section, so every section is visible on one page, as the spec's acceptance asks for Storage and the Danger zone.
- **General.**
  - **Name:** saved on blur or Enter; Escape keeps the saved name.
  - **Folder:** shown with its placement badge.
  - **Renaming** is `PATCH /projects/{pid} {name}`. It writes the descriptor and the registry; spaces are collapsed and the name is 1–120 characters. The folder itself is never renamed.
  - The S0 header's inline rename now uses the same endpoint.
- **Analysis.**
  - Three `SettingRow`s for the project keys: mode, AI cost limit per run, and send GPS. Each shows "From: this project / your preference / default", and Reset sends `null`.
  - `SettingRow` gains the `mode` source, with no Reset.
  - The other analysis parameters stay in S8; "More analysis settings…" opens it.
- **Devices.** Each camera shows its clip count, clock correction and LUT. "Check camera clocks…" opens S6's ClockCheckDialog, the same component as in S5.
- **Trip context.** A one-line summary (name, dates, days, people, must-include) and "Edit trip context", which opens S7.
- **Storage** (ADR 0051).
  - It shows the total, `StorageBreakdown`, "Clear regenerable files" and how much that frees.
  - The confirmation states the space freed, that previews are made again by the next analysis (until then clips and edits can't play), and what is kept.
  - While a clear runs, the button reads "Clearing…" and the page polls.
- **Danger zone.** "Remove…" opens a dialog that needs the project's exact name.
  - On success the app goes Home with a toast ("Your footage is untouched").
  - A refusal shows product copy for its reason (see below).
- **Read-only.** The project layout's banner says the project is open on another computer. Every control is disabled: inputs, the mode control, the switch, Clear and Remove. No Reset buttons are shown. A 409 from a settings save says the project is open read-only.
- **Type sizes come from the tokens.** Section titles and the storage total use `text-title` (24/30) rather than the mockup's 22 px and 28 px (ADR 0033, as ADR 0041 decided for S8).
- **The GPS row's copy** follows S8 ("Location stays on this computer. No analysis step uses it yet."). It claims no feature that doesn't exist (ADR 0041).
- **Removal refusals** are mapped to product copy (open elsewhere, read-only, work running). Any other refusal reads "Couldn't remove MosAic's data. Nothing was removed."

## Consequences

- The 5b carry-forward (the rename endpoint) is closed.
- S21's own copy follows the product's US spelling ("analyzed", "color").
