# 0057 — Desktop API access: per-launch token, one loopback origin

- Status: accepted (M3 step 1)
- Deciders: agent (autonomous; no human gate)

## Context

ARCHITECTURE.md §3 and §14 ask for three protections on the desktop API:
- a per-launch token from Tauri on every request;
- a Host-header allowlist against DNS rebinding;
- CORS limited to the Tauri origin.

M3 acceptance 2: a second local web page cannot call the backend.

Two facts shape the design:
- Media elements (`<video src>`, `<img src>`) and `EventSource` cannot send an `Authorization` header.
- Putting the token in URLs would put it in logs and history (invariant 11).

## Options

1. **The UI from `tauri://`, the API on `http://127.0.0.1:<port>`, a bearer header on `fetch`.** Media URLs would need signed query tokens, and CORS would have to allow the `tauri://` origin.
2. **One loopback origin for the UI and the API.** The webview loads `http://127.0.0.1:<port>/` from the backend, as the server mode does. The shell injects the token into its own webview, and the page trades it for an HttpOnly session cookie. Every request is then same-origin, and no CORS is needed at all.

## Decision

Option 2.

- **Token.** The shell starts `mosaic serve --port 0 --token-stdin` and writes a random token (32+ ASCII characters) as the first line of stdin. It never goes on the command line.
  - Stdin keeps it out of the process's environment block, which same-user tools such as `ps eww` can read.
  - `MOSAIC_DESKTOP_TOKEN` works too. `serve` removes it from its environment before the app, the worker supervisor or any child starts, and it is on `core.runtime.SECRET_ENV`, so FFmpeg, the probes and installed AI apps never see it.
  - A token that is given but empty, short or non-ASCII stops the start with an error. A shell bug must never mean an unprotected API.
- **Port.** `--port 0` binds a free port on `127.0.0.1` and prints `MOSAIC_READY port=<n>` once uvicorn accepts connections. The shell reads that line, so there is no port race.
- **A request is allowed** (`deps.principal`) when it carries:
  - `Authorization: Bearer <token>` (constant-time compare); or
  - the `mosaic_desktop` session cookie together with `Sec-Fetch-Site: same-origin`, or `none` for a navigation the user started.

  `POST /api/auth/desktop-session` (bearer only) issues the cookie: a random session id, never the token, HttpOnly and `SameSite=Strict`. Sessions live in memory, and a restarted sidecar has a new token anyway.
- **Why `Sec-Fetch-Site`.** A page on `http://127.0.0.1:<other port>` is the same *site*, so `SameSite=Strict` would still send it the cookie. Browsers set `Sec-Fetch-Site` themselves, and a page cannot forge or remove it. WebKit sends it from Safari 16.4 / macOS 13.3. The app's minimum macOS (decided in step 5) must be at least that. A client that sends no such header (curl with a stolen cookie) is refused too.
- **Host.** Unchanged: only `127.0.0.1` and `localhost` (421 otherwise).
- **CORS.** No `Access-Control-*` header is ever sent, so no other origin can read a response. A preflight from another origin fails, which blocks non-simple writes. Simple writes from another origin fail the session check.
- **Public routes:**
  - `/api/health` (returns only `{ok}`) and `/api/auth/status` (says whether this request is let in);
  - `/api/auth/setup` and `/login`, which are server-only and answer 404 on the desktop;
  - the UI's own files (`/`, `/assets/*`, the client routes), and `/docs` and `/openapi.json` on the desktop. They are the public build output and the API's shape, with no trip data, and no other origin can read them anyway.
- **The page.** `lib/desktop.ts` reads `window.__MOSAIC_DESKTOP__.token`, which the shell's initialization script injects only into its own webview. It sends the token once and deletes it. It never stores it. A plain browser tab opened on the port gets "Open MosAic from the app".
- **Without a token** (developers running `mosaic serve`, and the test suite), desktop mode keeps the M0 behaviour: loopback and Host only.

## Consequences

- **Verify first in the real webview (step 4).** `<video>` (AVFoundation), `<img>` and `EventSource` in WKWebView must send the cookie and `Sec-Fetch-Site: same-origin`. If one doesn't, this ADR gains a fallback, such as short-lived signed media URLs that never contain the token.

- The desktop and the server serve the UI the same way, and the frontend has no mode-specific transport.
- The shell must load the backend's URL in its webview. Tauri IPC (the native folder picker, the menu) is granted to that URL through a remote capability (step 4).
