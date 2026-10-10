# 0060 — The desktop shell: sidecar lifecycle, window, menu bar, sandboxing

- Status: accepted (M3 step 4)
- Deciders: agent (autonomous; no human gate)

## Context

M3 asks for:
- a Tauri 2 shell that loads the same React build;
- a sidecar lifecycle: a random port, a per-launch token, a health wait, a graceful shutdown that lets workers finish or checkpoint, and a crash restart with job resume;
- a native folder picker, with security-scoped bookmarks if sandboxed, or an ADR saying why it isn't;
- pause and resume from the menu bar;
- fewer workers on battery (a setting).

ADR 0057 fixed how the shell and the backend authenticate.

## Decision

- **Project.** `desktop/` holds the shell: `desktop/src-tauri` (Rust, Tauri 2.12, `tauri-plugin-dialog`, `ureq`, `getrandom`, `libc`, all MIT or Apache-2.0) and `desktop/package.json` for the Tauri CLI.
  - The shell holds no business logic (invariant 12). It starts the backend, shows its page, and forwards two menu commands.
- **Launch.** The shell makes a 32-byte random token and starts `serve --port 0 --token-stdin`:
  - in a release, the bundled Python (step 5);
  - in a development build, `uv run --frozen mosaic serve` in the repository.

  It writes the token as the first line of stdin, reads `MOSAIC_READY port=<n>` from stdout (90 s at most) and waits for `/api/health` (30 s). The backend's stdout and stderr go to `backend.log`: in `~/Library/Logs/com.mosaic.desktop/`, or `$MOSAIC_HOME/logs/` when that is set.
- **Lifeline.** The shell keeps the backend's stdin open while it lives. If the shell is killed or crashes, the pipe closes and the backend stops gracefully instead of running on as an orphan. This works on Windows too.
- **Window.** The shell loads the backend's own page, `http://127.0.0.1:<port>/`, and injects the token for that webview only (ADR 0057).
  - Navigation is limited to that origin, so links elsewhere never load in the app window.
  - Windows are labelled `main-<port>`, so a restarted backend gets a new window while the old one closes.
  - Closing the window doesn't quit. MosAic keeps working from the menu bar, as Mac apps do. The Dock icon and "Show MosAic" open the window again.
  - Development builds can open another page first (`MOSAIC_DEV_START_PATH`), which is used to test media in the real WKWebView. Release builds always open `/`.
- **Crash restart.** When the backend exits on its own, or fails to start, the shell starts it again with a new token and port, and the window follows. Jobs resume from the task log: their leases expire and the supervisor (ADR 0056) starts a worker. After 5 attempts within 2 minutes it stops trying and shows an error with the log's location. A backend that finishes starting after a quit began is stopped at once.
- **Quit.** ⌘Q is MosAic's own app-menu item ("Quit MosAic"), so it doesn't depend on how the platform reports a menu quit. The menu bar's Quit, a SIGTERM, SIGINT or SIGHUP to the shell, and any other exit request all take the same path:
  1. The windows close first, and their event streams with them.
  2. The shell closes the lifeline and sends SIGTERM, then waits up to 60 s before SIGKILL. The wait runs off the main thread, so the menu bar stays responsive.
  3. The backend's open requests are cut after 5 s (`timeout_graceful_shutdown`), so its lifespan cleanup always runs: the supervisor sends SIGTERM to the worker it started, and leases are released.
  4. The worker takes no new task and lets running ones finish for up to 30 s (it used to wait 10 s). A task still running then keeps its lease, and its job resumes from the task log on the next launch.
  5. A worker started on its own leads its process group. On the way out it ends the group's other members, such as an FFmpeg a cut-off task left behind. Outputs are renamed into place only on success (invariant 9).

  Verified with the real app: a quit during a Thorough analysis left no process behind after 31 s, and the next launch finished the job.

  The app menu also has the standard Edit items, so copy and paste work in text fields, plus Window → Minimize and Close.
- **Menu bar.** A template icon (the tile grid) with Show MosAic, Pause all work, Resume work and Quit MosAic.
  - Pause and Resume call the new `POST /api/jobs/pause-all` and `/resume-all` with the token.
  - Pause-all pauses every waiting or running job.
  - Resume-all resumes jobs paused by hand. A job paused at its AI cost limit waits for a higher limit (ADR 0018).
- **Battery.** A new setting, `workers.battery_saver` (on by default). When `hardware.on_battery()` says the Mac runs on battery (`pmset -g batt`; Linux reads `power_supply`), each resource class leases with about half its slots, never fewer than one. The power state is read every 30 s, and the extra slots resume on mains power.
- **Native folder picker.** Tauri's dialog plugin, granted to the backend's page only: a remote capability for `http://127.0.0.1:*`, permission `dialog:allow-open` and nothing else.
  - The capability matches any loopback port. The window's navigation lock to the backend's one port is what keeps other pages out of it.
  - `app.security.csp` is null because the page's policy is the backend's own `Content-Security-Policy` header, the same as on the server. In the Mac app, Home's Open folder and Reconnect use it. A refused folder then shows the typed-path dialog with the reason.
- **Not sandboxed.** The app is signed with the hardened runtime and notarized, but not App Sandboxed.
  - The Python backend opens footage folders across launches, re-reads them to relink moved files, writes `MosAic/` and `.mosaic-project.json` next to the footage, and runs FFmpeg and the probes on those files. Under the sandbox, every one of these needs a security-scoped bookmark resolved and started inside the Python process, and its child processes, for every folder and every launch. The Mac App Store, the only place that requires the sandbox, is not a distribution target.
  - What the sandbox would protect is covered otherwise:
    - originals are opened read-only (invariant 1);
    - the API is reachable only from the app's own webview (ADR 0057);
    - the webview may load only the backend's origin;
    - the dialog permission is the only native API the page can use.

- **Rust licenses.** The shell's crates (430 with `signal-hook`) carry MIT, Apache-2.0, BSD, ISC, Zlib, MPL-2.0 or Unlicense, plus three permissive licences outside CLAUDE.md's list that are accepted here: BSL-1.0 (Boost), 0BSD, and Apache-2.0 WITH LLVM-exception. The exceptions:
  - 19 ICU and Unicode data crates (`icu_*`, `zerovec`, `unicode-ident` and kin, pulled in by URL parsing) under **Unicode-3.0**. It is a permissive, OSI-approved licence requiring the notice to be kept, like MIT, so it is accepted here, as CLAUDE.md asks of a licence outside its list.
  - `r-efi`, which offers MIT among its options.

  `scripts/check_rust_licenses.py` evaluates each SPDX expression, with brackets, AND and OR, and fails on any crate outside that set. It runs in `make lint` when cargo is installed, and in `make desktop-check`.

## Consequences

- One process tree per launch: shell, backend, and workers started on demand. Nothing outlives the shell: the lifeline stops the backend, and the backend stops its workers.
- Battery saver and pause-all are backend features, so the web server gets them too. The server has no battery in practice, and the endpoints are behind sign-in.
- Windows needs `terminate` and `kill` (no-ops there today) and the folder picker's paths checked; that is a later milestone.
