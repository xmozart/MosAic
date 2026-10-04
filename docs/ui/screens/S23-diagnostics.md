# S23 — Diagnostics

- **Reference:** `docs/ui/reference/` → S23-Diagnostics
- **Milestone:** M2

**Purpose.** Troubleshooting for advanced users.

## Layout

Task table (task, input, status, tool/model, time, tokens, cost) beside a detail card (command, stderr, timings, attempts, worker, Retry/Skip).

Header action: Export diagnostic bundle (redacted).

## States

- Filtered by status.
- Task detail for success, failure and running tasks.

## Data & API

- `/diagnostics/tasks`, `/diagnostics/bundle`.

## Acceptance

- No secret ever appears (automated scan of the bundle).
