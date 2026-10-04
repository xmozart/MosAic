# S2 — Sign In

- **Reference:** `docs/ui/reference/` → S2-SignIn
- **Milestone:** M2

**Purpose.** Server mode only. A single admin account in v1.

## Layout

Centered 400 px card: mark and wordmark, title, password field, primary button.

First-time variant: password and confirm, with "Create account".

## States

- Wrong password: inline danger banner.
- Rate-limited after 5 failures: wait message with a countdown.

## Data & API

- `/auth/setup`, `/auth/login`.

## Keyboard

- Enter submits.

## Acceptance

- Cookie is HttpOnly and SameSite=Strict; CSRF token is required on all mutating requests.
