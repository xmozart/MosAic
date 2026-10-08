# 0055 — The server Docker image

- Status: accepted (M2 step 10)
- Deciders: agent (autonomous; no human gate)

## Context

M2 asks for a multi-arch image (amd64, arm64) with LGPL FFmpeg, compose examples (plain, plus an optional NVIDIA runtime), a healthcheck and a document on the volume layout. Acceptance 1 is a fresh `docker compose up` with one media root that reaches a rendered preview from the browser.

The rest of the server side already existed in M2 step 3:
- server mode;
- the sign-in cookie with CSRF protection;
- the server's secret stores (environment, Docker secrets, an encrypted file with a master key);
- configured media roots;
- the bind address and allowed hosts;
- serving the built UI.

## Decision

- **One image, three stages** (`Dockerfile`).
  - **Web UI:** `node:24` on the build platform, `npm ci` and `npm run build`. The UI is plain files, so it doesn't depend on the target architecture.
  - **FFmpeg:** BtbN's static LGPL build, chosen per architecture (`linux64-lgpl` or `linuxarm64-lgpl`).
    - It is pinned to one dated release, with a SHA-256 for each architecture as build arguments. `uv` is pinned too (0.10.8).
    - The stage fails if the build reports `--enable-gpl`. It brings NVENC and OpenH264, and never x264 or x265.
  - **Runtime:** `python:3.12-slim-bookworm`. The environment comes from `uv.lock` with `--frozen --no-dev`; PyAV stays excluded (ADR 0009).
  - The image runs as user `mosaic` (uid 1000), never root. `/data` is a volume and the footage mounts at `/media`.
  - The image sets `MOSAIC_MODE=server`, `MOSAIC_HOME=/data`, `MOSAIC_UI_DIR=/app/ui` and `MOSAIC_MEDIA_ROOTS=/media`, and runs `mosaic serve --port 8765`. Workers start on demand inside the container, as on the desktop.
- **Live databases stay in `/data` (invariant 2).**
  - A bind mount doesn't reveal its storage: Docker Desktop shares host folders over `virtiofs`, which may be a NAS or a cloud-synced folder.
  - The classifier treats host-share filesystems (`virtiofs`, `fakeowner`, `grpcfuse`, `osxfs`, `vboxsf`, `prl_fs`) as network shares.
  - The image also sets `MOSAIC_FOLDER_DB=never`. Under it, a folder that would be in-folder becomes split, and `assert_live_db_allowed` refuses any live database outside app data.
  - A trip made in-folder on the desktop is moved to split the first time it is opened for editing, under the project's lease, with its database and cache copied to app data.
    - From the browser, the move is a `project.move` job, never part of a request (invariant 8): copying a trip's cache can take minutes. `POST /projects` and `POST /projects/{pid}/open` register the trip and return `moving_job`. Until the job ends, the trip's other routes answer 409, and the UI shows "Moving this trip's data to MosAic's storage" with the job's progress, then the trip's screens.
    - Create returns before taking the lease or submitting a scan. After the move, the trip behaves like one not yet opened: reads work, writes take the lease per request, and opening it from Home holds the lease as usual. If the move fails (another computer holds the lease, for example), routes keep answering 409 with a reason that says to open the trip from Home, which starts a new move.
    - The CLI, a separate process with no request to block, still moves the trip inline.
    - The move is one-way. The trip stays split when it is opened on the desktop again: its live database and cache now live in that MosAic's app data, and the folder keeps the `MosAic/` outputs and the database snapshot.
    - A read-only open is refused with a reason ("open it for editing once"), and so is asking for in-folder placement there.
    - Copying reads the old database in the folder once (the SQLite backup API), which may briefly create `-wal`/`-shm` files there. It is a one-time migration, accepted.
  - The S4 preview reports the placement creation will use (split). A split trip on a local disk shows the "Stored separately" badge, not "NAS".
  - The `MosAic/` folder next to the footage keeps previews, renders, edit files and a database snapshot.
- **Healthcheck.** `GET /api/health` needs no sign-in and passes no host check. It checks that the control DB answers and returns only `{ok}`; a broken DB is a 500. It is listed in the auth test's public routes. The image's `HEALTHCHECK` calls it by loopback with Python, so no curl is needed.
- **Compose.**
  - `compose.yaml`: one service with port 8765, the `mosaic-data` volume and the footage at `/media`.
    - The footage is read-write by default, so trips keep their `MosAic/` folder next to the footage (in-folder placement).
    - The doc explains `:ro` (external placement in `/data`).
    - The master key is a Docker secret read from `master_key.txt`. One `openssl rand` command creates it. Without it, keys typed in Settings couldn't be stored (ADR 0036).
  - `compose.nvidia.yaml`: an override that reserves NVIDIA GPUs.
  - `init: true` reaps the job workers MosAic starts and passes them `docker stop`'s signal.
  - **The master key file is a one-time host step** (`openssl rand …`) before the first `up`. It is not use of MosAic's CLI, so acceptance 1 still holds.
  - `MOSAIC_MEDIA_ROOTS` accepts commas as well as the path separator.
- **Lock file.** `npm ci` on Linux needs the WebAssembly fallback's peer dependencies (`@emnapi/core`, `@emnapi/runtime`) to be pinned. They are now explicit dev dependencies (MIT, not shipped).
- **Volume layout doc:** `docs/deploy/DOCKER.md` covers:
  - volumes and what to back up;
  - read-only footage and several media roots;
  - settings and secrets;
  - TLS and a reverse proxy (cookies are always `Secure`, so plain HTTP works only on localhost);
  - NVIDIA, health and logs, and building the image.
- **`make docker`** builds the image for this machine and checks that it:
  - becomes healthy, serves the UI and runs in server mode;
  - has an FFmpeg with no GPL parts;
  - runs as a non-root user;
  - keeps the master key out of its Env (passed as a file secret, as in compose);
  - keeps live databases in `/data`.
- **Static test.** A unit test checks `compose.yaml` and the Dockerfile without Docker: the secret, the non-root user, the policy variable and the pinned digests. It is not part of `make ci`, which runs on machines without Docker. Step 11 runs the compose end-to-end test.

## Consequences

- The image is about 1.3 GB, mostly the Python wheels (ctranslate2, scipy, numpy) and FFmpeg. Models download into `/data/models` on first use.
- A release workflow (registry push, signing) belongs to the packaging milestone, not M2.
