# Running MosAic with Docker

The server image runs the MosAic backend, the web UI and its job workers in one container. FFmpeg inside it is an LGPL build, run as a separate process.

## Quick start

```bash
openssl rand -base64 48 > master_key.txt      # encrypts the API keys you type into Settings
MOSAIC_MEDIA=/path/to/your/trips docker compose up -d
```

Then open <http://localhost:8765>.
1. Set the admin password.
2. Open a trip folder from the media root.
3. Run the analysis and create an edit.

You add your AI provider's key in **Settings → AI providers**.

## Volumes

| Mount | What lives there | Back it up? |
|---|---|---|
| `/data` (`mosaic-data` volume) | The control DB (users, settings, jobs and history), the encrypted key file, downloaded models (`models/`), logs, and **every trip's live database** with its analysis cache (`projects/<id>/`). | Yes, except `models/`, which downloads again. |
| `/media` (your footage, `MOSAIC_MEDIA`) | Your trip folders. MosAic never changes, moves or deletes an original. For each trip it opened, it writes a `MosAic/` folder and a small `.mosaic-project.json` next to the footage. The `MosAic/` folder holds previews, renders, edit files and a snapshot of the trip's database. | It is your footage. `MosAic/` folders can be backed up with it. |

**Why the live database stays in `/data`.** The image sets `MOSAIC_FOLDER_DB=never`. A bind mount doesn't reveal what backs it: Docker Desktop shares host folders through `virtiofs`, and the folder can be a NAS or a cloud-synced folder. A live SQLite database there can be corrupted (invariant 2). MosAic therefore uses the *split* placement:
- the live database stays in the `/data` volume;
- a consistent snapshot is written next to the footage at checkpoints, so the trip can be opened on another computer.

A trip made on the desktop with its database in the folder is moved to split the first time the server opens it. The move runs as a background job, so the trip shows "Moving this trip's data…" for a short while. It happens once, and your footage isn't touched.

**Read-only footage.** Mount it read-only (`${MOSAIC_MEDIA}:/media:ro`) to keep even those files out of it. MosAic then keeps every trip's data in `/data/projects/` and finds the trip again by its folder. This is the *external* placement (ARCHITECTURE.md §4).

**Several media roots.** Mount more folders, for example `/media/nas` and `/media/archive`, and list them in `MOSAIC_MEDIA_ROOTS`, separated by commas or colons (`/media/nas,/media/archive`). An admin can also add roots in **Settings → Media roots**. Only folders inside a media root can be opened.

**Permissions.** MosAic runs as uid 1000 inside the container.
- **Footage:** it needs write access to a trip folder to create `MosAic/` there. Otherwise it keeps everything in `/data` (external placement), as with `:ro`.
- **`/data` as a host folder:** if you bind-mount a host folder for `/data` instead of the named volume, make it writable first, with `sudo chown 1000:1000 ./data`.
- **The default `./media`:** compose creates it as root on Linux when it doesn't exist yet. Create it yourself first.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MOSAIC_MEDIA_ROOTS` | `/media` | Folders people can open, inside the container, separated by commas or colons. |
| `MOSAIC_FOLDER_DB` | `never` (in the image) | Keeps every live database in `/data` (see Volumes). Leave it set. |
| `MOSAIC_ALLOWED_HOSTS` | any | Host names browsers use, comma-separated. Set it when MosAic is reachable from a network. |
| `MOSAIC_MASTER_KEY_FILE` / `MOSAIC_MASTER_KEY` | — | 32+ random characters. They encrypt API keys typed in Settings. Without one, keys can still come from the environment or Docker secrets. |
| `MOSAIC_SECRET_AI_ANTHROPIC` (or the Docker secret `mosaic_ai_anthropic`) | — | An API key the deployment provides. A key typed in Settings is used instead; removing it there goes back to this one. |
| `MOSAIC_PORT` (compose) | `8765` | The port on the host that `compose.yaml` publishes. |
| `MOSAIC_BIND` | `0.0.0.0` | The address the server listens on, inside the container. |
| `MOSAIC_COOKIE_SECURE` | `1` | `0` allows sign-in over plain HTTP from another machine. Use it only on a trusted test network; use TLS instead. |

API keys never appear in responses, logs, the project folders, browser storage or the diagnostic bundle.

## TLS and a reverse proxy

MosAic speaks plain HTTP on port 8765. Its sign-in cookies are always `Secure`. Browsers accept them on `http://localhost`, so the quick start works on the machine that runs Docker.

From any other machine, reach MosAic through a reverse proxy with TLS (Caddy, Traefik or nginx), and set `MOSAIC_ALLOWED_HOSTS` to the public name. Over plain HTTP from another machine, the browser drops the cookie and sign-in fails. `MOSAIC_COOKIE_SECURE=0` lifts that, but only for a trusted test network.

## NVIDIA GPUs

```bash
docker compose -f compose.yaml -f compose.nvidia.yaml up -d
```

You need the NVIDIA Container Toolkit on the host. Renders then use NVENC (`h264_nvenc`). Without a GPU, the image encodes with OpenH264. x264 and x265 are GPL and are never included.

## Health and logs

- `GET /api/health` answers without sign-in. It is the container's healthcheck, and a proxy can use it too.
- The server's logs go to the container's output (`docker compose logs -f`). The server starts a job worker whenever there is work, and it exits after 20 s idle (ADR 0056). The workers log to `/data/logs/worker.log`.
- The first analysis downloads its models (over 1 GB) into `/data/models`. On a home connection that took about 20 minutes once; later analyses start at once.
- **Settings → Diagnostics** exports a redacted bundle for support.

## Building the image

FFmpeg comes from one pinned BtbN release, checked by SHA-256 for each architecture. To move to a newer release, set the three build arguments from that release's asset digests:
- `FFMPEG_TAG` (for example `autobuild-2026-10-07-13-07`) and `FFMPEG_NAME`;
- `FFMPEG_SHA256_AMD64` and `FFMPEG_SHA256_ARM64`.

The build fails if a digest doesn't match, or if the build is GPL.


```bash
docker buildx build --platform linux/amd64,linux/arm64 -t mosaic:latest .   # multi-arch
make docker                                                                # this machine's arch, plus a smoke test
make docker-e2e                                                            # compose up, then a trip to a rendered preview over the API
```
