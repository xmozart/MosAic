# CLAUDE.md — MosAic

You are building MosAic, an application that turns a folder of raw trip footage and photos into a finished, story-driven video. It analyzes footage once into a semantic library, then generates many edits from that library.

Read before any structural work: `docs/ARCHITECTURE.md`. Read the current milestone file in `docs/milestones/`. Other docs are referenced from there.

For any frontend work, read `docs/ui/README.md` first, then the relevant `docs/ui/screens/S##-*.md`, `docs/ui/COMPONENTS.md` and `docs/ui/DESIGN_TOKENS.md`. The `docs/ui/reference/*.dc.html` files are approved mockups: match their layout, sizes and copy, but build from components and tokens. Never copy their inline styles into the product.

## Working agreement

**You work autonomously.** Follow `docs/AGENT_WORKFLOW.md`:
- plan, implement, test, self-review with the `spec-reviewer` subagent, commit, and continue
- go through milestones in order without asking for approval
- stop **only** at the human gates listed there (G1–G7)

On every session start:
1. Read `CLAUDE.md`, `docs/AGENT_WORKFLOW.md` and `docs/STATUS.md`.
2. Resume from the first unfinished step.

Scope and quality rules:
- Implement **only the current milestone's scope**. Items listed as out of scope, and everything in `docs/FUTURE_APPENDIX.md`, must not be built. They must also not be made impossible by your design choices.
- When the spec is ambiguous or evidence contradicts it, decide, write an ADR in `docs/decisions/NNNN-title.md` (context, options, decision, consequences), update the affected doc, and continue. Never silently diverge, and never stop just to ask unless a human gate applies.
- Owner decisions already made are in `docs/decisions/` (start with 0002). Don't re-open them.
- A milestone is complete only when its acceptance tests pass in `make ci` and its report is written.
- Make small commits, each with tests. Never weaken or skip a failing test to make progress.

## Invariants (never violate)

1. **Originals are read-only.** Never modify, move, rename or delete source media. Open source files read-only.
2. **Storage placement is decided by policy** (`ARCHITECTURE.md §4`). Never write a live SQLite database to a network or cloud-synced filesystem.
3. **Time is exact.** Authoritative times are integers:
   - `SourceTime` = integer ticks in the source stream's time base: `{"ticks": 4026240, "tb": "1/90000"}`
   - `TimelineTime` = integer frames at the timeline rate: `{"frames": 1724, "rate": "30000/1001"}`
   Floating-point seconds are allowed only for display and for transient computation inside a function. They are never stored or passed across a module boundary as authoritative values. All examples in these docs follow this rule; copy the examples.
4. **Analysis is keyed to source PTS**, never to proxy frame indices.
5. **AI produces decisions, not media operations and not timeline arithmetic.** AI output never contains FFmpeg commands or timeline positions. Positions come from the deterministic solver (`ARCHITECTURE.md §9`).
6. **Every AI response is validated** against a Pydantic schema. Invalid output is retried with the validation error, then fails the task. It is never partially accepted.
7. **The database is the source of truth.** JSON files for edits and exports are derived artifacts written on commit.
8. **All long work runs as jobs** in the DAG queue. HTTP handlers only create, query or cancel jobs.
9. **Every artifact is idempotent and provenance-stamped.** Its key is a hash of inputs, config and algorithm or prompt version. Identical keys mean no recompute.
10. **User decisions override AI.** Ratings, locks, USE/REJECT and manual edits are hard constraints until the user resets them.
11. **Secrets never touch project files, the DB, browser storage, logs, process argv or exports.** Config stores only a `secret_ref`.
12. **One codebase.** Server and desktop share the same frontend, backend and project format. No forked business logic.
13. **Any length, any mix.** Never load a whole project into memory. Paginate, stream and process per asset.
14. **Graceful unsupported media.** Unknown or undecodable files are listed as unsupported with a reason. They never crash a scan or a job.
15. **The UI follows the approved design.** Tokens come only from `docs/ui/tokens.json`. The AI-vs-you visual rule is mandatory. Fonts are bundled (Geist, SIL OFL), never fetched at runtime.
16. **Don't invent facts.** Titles and captions may name places or people only if they come from trip context, metadata or explicit user input.

## Dependency licensing (enforced from day one)

The product may become commercial.

- Allowed without review: MIT, BSD, Apache-2.0, ISC, MPL-2.0, PSF, zlib, HPND / MIT-CMU (Pillow), WTFPL (libzimg), SIL OFL (fonts), Unlicense / CC0 / public domain. CC-BY-4.0 is allowed for **test fixtures only**, with attribution.
- LGPL is allowed only when dynamically linked or used as a separate process. FFmpeg must be an **LGPL build invoked as a subprocess**.
- Not allowed without an explicit ADR: GPL (including GPL FFmpeg components such as libx264 and libx265), AGPL, SSPL, and any non-commercial or research-only model weights.
- Encoding uses platform hardware encoders (VideoToolbox, NVENC, QSV, AMF) by default. Software x264/x265 may exist only as an optional, user-installed FFmpeg.
- Record every runtime dependency and model in `LICENSES.md` (name, version, license, how it is used).

## Stack and conventions

**Backend**
- Python 3.12, managed with `uv`.
- FastAPI, Pydantic v2, SQLAlchemy 2 with Alembic migrations (separate migration trees for the control DB and the project DB).
- pytest, ruff, mypy (strict for `core/` and `media/`).

**Frontend**
- React, TypeScript (strict), Vite, Tailwind, shadcn/ui, Zustand, TanStack Query.
- Vitest for tests.

**Desktop**
- Tauri 2, with the Python backend as a sidecar.

**Media**
- FFmpeg/ffprobe (LGPL build), PySceneDetect, OpenCV (headless).
- Local Whisper-compatible STT (faster-whisper).
- SigLIP or OpenCLIP image embeddings.
- sqlite-vec.

**Code conventions**
- Build FFmpeg invocations only through `media/ffmpeg/` builders. Never assemble raw command strings elsewhere.
- Keep all prompts as versioned files in `ai/prompts/<name>/v<N>.md` alongside their Pydantic output schema.
- AI providers and models are app settings, never hard-coded; only `ai/adapters/<provider>/` imports a provider SDK (ADR 0003).

## Things not to build yet

- Multi-user, roles UI, tenants, OIDC/SAML, PostgreSQL.
- Celery/Redis, Kubernetes, distributed workers.
- OTIO/FCPXML exporters. The data model must stay OTIO-mappable, but exporters come in a later milestone.
- 360° reframing of raw Insta360 footage (a later milestone).
- Face recognition or named-people identification.
- Music-driven editing until its milestone.
