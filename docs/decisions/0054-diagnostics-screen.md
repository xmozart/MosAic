# 0054 — The diagnostics screen (S23)

- Status: accepted (M2 step 9d)
- Deciders: agent (autonomous; no human gate)

## Context

S23's mockup shows a task table on the left (task, input, status, tool or model, time, tokens, cost). On the right is one task's detail (command, stderr, started, duration, attempts, worker, Retry and "Skip file"). "Export diagnostic bundle (redacted)" sits in the header.

The spec lists two states: a table filtered by status, and the detail of a task that succeeded, failed or is still running. Its acceptance criterion: no secret ever appears in the bundle (ADR 0051's backend, and its test).

## Decision

- **Route.** `/diagnostics?status=&project=`. It is reached from S22's About ("Diagnostics…") and the command palette, and the rail's Settings item stays lit there.
- **Filters:**
  - **Status:** All, Failed, Running (`leased`), Waiting (`ready`) or Done, as a segmented control.
  - **Trip:** a select of the user's trips.
  - Both live in the URL, so a filtered view can be shared or reloaded. An unknown status means All.
  - The selected task belongs to one filter: changing the filter or the trip, or going back or forward, hides it until that filter shows again.
- **The table** pages 100 rows at a time ("Show more"). It polls every 3 s while a listed task is pending, waiting or running, and so does an open task's detail. Each row shows:
  - the task kind and its input label;
  - the status in words, coloured with tokens (`use` done, `reject` failed, `accent` running);
  - the tool or model;
  - the time, tokens and cost.
- **The detail:**
  - error output (redacted by the backend);
  - started, duration, attempts ("2 of 3") and worker;
  - for AI tasks, tool, tokens, cost and job;
  - parameters, folded away;
  - Retry and Skip, enabled only where the backend allows them. Success and running details say "Retry and Skip are for failed tasks", and a cancelled one says "Skip is for failed tasks". A refused action shows the server's reason.
  - A detail that can't be loaded (for example, the task of a removed trip) says so instead of loading for ever.
  - **Skip** is labelled "Skip", not "Skip file". It skips a task, which is not always a file.
  - **The "Command" block is not shown**, because tasks don't record their command lines (ADR 0051).
- **Export** downloads `POST /diagnostics/bundle` as `mosaic-diagnostics.zip`, redacted as ADR 0051 describes. The download link is added to the page, and its object URL is revoked a second later, so WebKit (the desktop webview) completes the download.

## Consequences

- With Diagnostics done, step 9 is complete: S21, S22 and S23 are all built.
