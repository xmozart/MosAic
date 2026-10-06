# 0034 — Server-mode sign-in, sessions and CSRF

- Status: accepted (M2 step 3a)
- Deciders: agent (autonomous; no human gate)

## Context

M2 adds the server deployment, with these requirements:
- ARCHITECTURE.md §3: a single admin account, an Argon2 password hash, an HttpOnly SameSite cookie and a CSRF token.
- S2: a wrong password shows an inline banner; after 5 failures, a countdown; the cookie is HttpOnly and SameSite=Strict; every mutating request needs a CSRF token.

The desktop app keeps binding to loopback. Its per-launch token arrives with Tauri in M3.

## Decision

- **Mode.** `MOSAIC_MODE=server` turns server mode on; the default is desktop, which is unchanged.
  - In server mode, the API binds to `MOSAIC_BIND` (default `0.0.0.0`, for a container behind a reverse proxy) and honours proxy headers.
  - The Host allowlist becomes `MOSAIC_ALLOWED_HOSTS`, or any host when unset, because the proxy owns the public name.
- **Account.** A single row in the control DB's `admin_account` holds the argon2-cffi hash with its default parameters. The hash is rehashed on login if the parameters change.
  - `POST /auth/setup` works only while no account exists.
  - The password needs at least 12 characters.
- **Sessions.** A 32-byte random token goes in the `mosaic_session` cookie: HttpOnly, SameSite=Strict, Secure, with path `/`.
  - The DB keeps only its SHA-256.
  - Sessions expire after 12 hours idle or 7 days absolute. Expired rows are pruned when new sessions are created.
  - Logout deletes the row.
- **CSRF.** Double submit.
  - Each session gets a random CSRF token, stored as a SHA-256 hash.
  - The token is returned in the setup/login response and in a readable, SameSite=Strict `mosaic_csrf` cookie.
  - Every POST, PUT, PATCH or DELETE must send it in `X-CSRF-Token`; it is compared in constant time.
  - The API client adds the header from the cookie.
- **Cross-site sign-in.** The public `setup` and `login` POSTs can't carry a CSRF token yet. They check instead that the Host is allowed (DNS rebinding) and that a browser's `Origin`, which browsers send on cross-site POSTs, is this host. This stops a hostile page from claiming a fresh server's account or forcing a login.
- **Brute force.** Five attempts from one client address lock it for 30 s. Each further lock doubles, up to 15 minutes.
  - An attempt is counted before the password check, so parallel guesses can't pass the lock.
  - A client is forgotten once its last lock ended a full maximum lock ago, which keeps memory bounded.
  - The response is 429 with `Retry-After` and `retry_after`, which drives S2's countdown.
  - The lock is kept in memory (one API process).
  - A missing account still costs one Argon2 hash, so response timing gives nothing away.
- **`MOSAIC_COOKIE_SECURE=0`.** It drops the Secure flag, for plain-http testing on a LAN. Browsers already treat `http://localhost` as secure, so a local compose works without it.
- **Security headers** on every response:
  - A Content-Security-Policy:
    - `default-src 'self'`;
    - scripts from this origin plus the SHA-256 of `index.html`'s inline theme script, computed from the built file at start-up;
    - `style-src 'unsafe-inline'`, needed for React style props;
    - `frame-ancestors 'none'` and `object-src 'none'`.
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY` and COOP.
  - `Cache-Control: no-store` on `/api`.
- **Public routes:** `/api/auth/status`, `/api/auth/setup` and `/api/auth/login`, plus the static UI. Every other `/api` route requires a session, and a test walks the OpenAPI paths to check that.
- **API docs.** `/docs` and `/redoc` are off in server mode.
- **Behind a reverse proxy.** uvicorn trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS`, which defaults to 127.0.0.1. In Docker it must be set to the proxy container's address, and never `*`:
  - With it unset, every client appears as the proxy, so all clients share one lockout.
  - With `*`, anyone can spoof the header and bypass the lockout.
  - The compose files (step 10) document this.
- **TLS and HSTS** are the proxy's job.

## Consequences

- The security headers apply in desktop mode too. M3 (Tauri) may need `connect-src` entries for its IPC scheme; add them there.

- Admin-only routes (media roots, step 3b) need no extra role check in v1: the only account is the admin. Multi-user stays out of scope (FUTURE_APPENDIX), and `authz.check` is still called on every request.
- If several API processes ever run, the lockout counter needs shared storage. The current deployment is one process (ADR 0002 K).
