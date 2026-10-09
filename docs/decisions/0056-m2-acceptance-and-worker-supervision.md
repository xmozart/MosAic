# 0056 — M2 acceptance runs, and the server supervises its workers

- Status: accepted (M2 step 11)
- Deciders: agent (autonomous; no human gate)

## Context

M2 acceptance 1 is "a fresh `docker compose up` with one media root reaches a first rendered preview edit from the browser without any CLI use". Acceptance 3 asks for an automated scan for API keys after an end-to-end test. Acceptance 4 asks for filter changes under 300 ms on a 5,000-item library. A milestone is complete only when its acceptance tests pass in `make ci`.

Building an image and running a container needs Docker and, on a first run, network access to download the analysis models. `make ci` runs on machines without either.

Running acceptance 1 against a real container found a defect: nothing started a job worker for jobs created over HTTP. The CLI starts a worker for the job it follows (`jobs.client.ensure_worker`), and the tests run jobs on in-process workers. The server itself never started one, so a job created from the browser stayed queued. ADR 0055 wrongly said workers start on demand.

## Options

1. Run the Docker flow inside `make ci`. This makes CI depend on Docker, a network connection and an image build of several minutes.
2. Run the same flow twice: in process inside `make ci`, and against a real container through a separate script, with its result recorded in the milestone report.
3. Start workers from each route that submits a job. Pause, resume, retry, re-render and restarts would each need it, and one missed path leaves a job stuck.
4. Have the server supervise workers: start one whenever runnable work exists and no live worker is registered.

## Decision

- **Options 2 and 4.**
- **In CI.** `tests/acceptance/test_m2_browser_flow.py` makes the web UI's calls in server mode:
  - first-run setup;
  - key entry, last 4 and validation;
  - provider choice and media root;
  - folder browse and preview;
  - create and scan;
  - quick analysis;
  - edit estimate and creation;
  - preview render and ranged playback;
  - the report.

  No CLI is used and no service is called directly. Jobs run on an in-process worker. The test then scans every API exchange, the log records, all of app data and the media folder for the key, both in full and without its last 4.
  - Browser storage is covered by the frontend tests: `AppSettings.test.tsx` and `System.test.tsx`.
- **Against the container.** `scripts/docker-e2e.sh` (`make docker-e2e`) generates a few corpus clips and runs `docker compose up --build` with them as the media root. `scripts/docker_e2e.py` then makes the same calls over HTTP with the standard library and follows each job until it is done. The compose project and its volume are removed afterwards. Its output goes into the M2 report.
- **`docs/ui/API_MAP.md` and the OpenAPI schema.** `tests/acceptance/test_m2_openapi.py` checks that every endpoint the map lists for an M2 screen exists in the committed schema. It also checks that the committed schema matches the server's paths. Rows marked "not in M2" are skipped: the AI critic's findings (M4) and Reveal (desktop).
- **5,000 clips.** `tests/acceptance/test_m2_library_scale.py` analyses four corpus clips. It clones their library rows to 5,000 clips spread over five days, with mixed decisions and tags. It then times one request per filter change against the 300 ms budget. The ≤ 60 mounted tiles are tested in `Library.test.tsx`.
- **The edit estimate** gets a budget on the 40-hour fixture: 2 s per request, in `test_m1_scale.py`.
  - Its first run took 7.4 s. Nearly all of it was `segment_facts`, which loaded about 630,000 metric rows as ORM objects and compared each segment with every metric of its clip.
  - The metrics are now read as plain rows and indexed by time per clip, so a segment looks only at its own range. The estimate now takes about 1.3 s.
  - The same function feeds the dispositions stage and retrieval, so analysis and edit generation gain too.
  - `tests/unit/test_segment_facts.py` checks the result against the old plain scan on random data, including one-frame segments and frame boundaries.
- **Worker supervision** (`jobs/supervisor.py`):
  - `mosaic serve` creates the app with `supervise_workers=True`. A background loop checks once a second. When a job is pending or running and no live worker is registered, it starts one with `start_worker` and gives it the registration grace period.
  - Workers still exit after 20 s idle, so an idle server holds no worker process. Paused jobs wait for the user.
  - A worker that exits within 10 s of starting (a broken install, an unwritable `/data`) is retried after a wait that doubles from 2 s up to 60 s. A worker that is still unregistered after the grace period is stopped (killed if it ignores the signal) and replaced after the same backoff.
  - Apps built by tests don't supervise, so test processes never spawn workers.
  - The desktop (M3) runs the same `serve`, so this is shared code (invariant 12).

- **Visual regression** (acceptance 7): `frontend/scripts/visual.mjs` serves the built Storybook and renders every story in both themes in headless Chromium.
  - `npm run visual` (part of `make frontend`) runs it inside the pinned Playwright image (`mcr.microsoft.com/playwright:v<version>-noble`; `scripts/visual-docker.sh` takes the version from the exact `playwright` dev dependency). macOS and Linux render text differently, and the container gives one Chromium, one font stack and one rasterizer on every host. One set of baselines then serves the owner's Mac and the Linux CI. `npm run visual:local` runs it on the host for a quick look. `make ci` therefore needs Docker on every host. Without Docker, `visual:local` still runs, but against baselines that won't match that machine's rendering.
  - Settings: 1280 × 800, animations off, a fixed clock (2026-07-20 12:00 UTC), UTC time zone, `en-US`.
  - Each render is compared with its baseline in `frontend/visual/`. More than 0.1 % of pixels differing fails, and the diff and the actual render go to `frontend/visual-diff/`. `--update` rewrites the baselines after an intended change.
  - Tools: Playwright (Apache-2.0), pixelmatch (ISC) and pngjs (MIT), all development only.
  - A story without a baseline, or one that doesn't render, fails the run: it is never accepted silently. `--update` also deletes the baselines of stories that no longer exist.
  - The baselines are about 40 MB of PNGs in git. If they churn, move `frontend/visual/` to Git LFS.
- **Structural review against `docs/ui/reference/`** (acceptance 6): the reference mockups are rendered to images and reviewed screen by screen against the story renders. The result goes into the M2 report.
  - The review found no structural deviation without an ADR. It found four smaller differences:
    - **S10's preliminary banner** lacked the mockup's "View progress" action. It now has it.
    - **S10's toolbar has two rows:** a full-width search field, then the filter chips. The mockup has one row behind a search icon. Kept: search is S10's main entry (S12), and the chips need the width at 1280 px.
    - **S25's day list is one column.** The mockup has two. Kept: each row carries its estimate and selection, which two columns truncate at 1280 px.
    - **S4's folder browser** shows one chip per media root, not one pill inside the breadcrumb. Kept: switching roots is one click.

    The review also asked for a story of the assembled S0 shell and of S3 with trips (heading and both Open buttons). Both are added (`Shell/AppShellScreen`, `S3/WithTrips`).
- **Radius tokens.** The screens used the mockups' radii (3–20 px) as arbitrary values. Invariant 15 allows only `tokens.json`, so each now uses the token its use names:
  - chips, keys and small marks (3–7 px): `sm` (6);
  - inputs, buttons, thumbnails, cards, banners and toasts (8 and 12 px): `md` (10);
  - dialogs, panels and the sign-in card (16–20 px): `lg` (14).

  `src/test/classes.test.ts` fails on any arbitrary radius. Outline offsets keep Tailwind's numeric `outline-offset-2`, as border widths keep theirs: `tokens.json` has no outline scale.
- **One Tab stop per radio group.** The wizard's length, shape and story choices, the analysis modes, the privacy mode and the star rating use `components/ui/RadioGroup`. The checked option (or the first enabled one) is the group's only Tab stop, and the arrow keys move the choice (the ARIA radio pattern). Radix's `ToggleGroup` (Segmented) already did this.
- **S20 polling.** While a render runs, only the first page polls: running renders are the newest. Every loaded page polls only if a running row sits further down. When the last running render ends, the loaded pages refresh once.

## Consequences

- Jobs created from the browser now run, as do jobs left unfinished when the server restarts. Pause, resume, retry and re-render all work through the same check.
- `make ci` proves the HTTP flow and the secret scan on every run. The Docker run is a separate command, run at each milestone and before a release; the M2 report records its result.
- The worker inherits the server's environment, including the master key (ADR 0036 already allows this).
