# MosAic — Specification Set v6

This folder replaces the single `ai_video_editor_implementation_plan_v3.md`. The content is the same product, reorganized so Claude Code can follow it without tripping over contradictions, and updated with the v3 review decisions.

## Files

| File | Purpose | When Claude Code reads it |
|---|---|---|
| `CLAUDE.md` | Invariants, conventions, rules, what not to build | Always (place at repo root) |
| `docs/PRODUCT.md` | Vision, user workflow, screens, settings catalog | When building UI or product behaviour |
| `docs/ARCHITECTURE.md` | Topology, storage placement, job DAG, data model, timebase, AI layer, editing pipeline, rendering, security, packaging | Always, before any structural change |
| `docs/MEDIA_SUPPORT.md` | Camera/format support matrix (iPhone, GoPro, Insta360, Nikon, DJI, photos) and camera-profile plug-in model | When touching ingest, probing, proxies, color, rendering |
| `docs/ANALYSIS_MODES.md` | Quick / Balanced / Thorough / Custom analysis profiles, progressive deepening, estimates | When touching analysis orchestration |
| `docs/EVALUATION.md` | Fixture corpus, metrics, regression harness | From M0 onward |
| `docs/milestones/M0.md` … `M4.md` | Detailed milestone specs with acceptance tests | One at a time |
| `docs/milestones/LATER.md` | M5+ outline (audio mix, music, AI review, timeline UI, 360 reframing, Windows, NLE export) | Planning only |
| `docs/FUTURE_APPENDIX.md` | Multi-user, multi-tenant, scale-out, commercial hardening. **Do not build; do not preclude.** | Only when a design choice might block it |
| `docs/ui/README.md` | UI authority, screen index S0–S26, rules | Before any frontend work |
| `docs/ui/DESIGN_TOKENS.md`, `docs/ui/tokens.json` | Approved tokens and Tailwind/shadcn mapping | M2 onward |
| `docs/ui/COMPONENTS.md` | Shared components, props and states | M2 onward |
| `docs/ui/API_MAP.md` | Endpoints and SSE events the screens need | M0 (backend shapes) onward |
| `docs/ui/screens/` | 27 screen specs: layout, states, data, keyboard, acceptance | Per milestone |
| `docs/ui/reference/` | Exported approved artboards (`.dc.html`) | Visual reference |
| `docs/ui/brand/` | Logo SVGs and voice and copy rules | M2 onward |
| `docs/AGENT_WORKFLOW.md` | Autonomous development protocol: the loop, self-sufficiency rules, human gates G1–G7, budgets | Always |
| `docs/STATUS.md` | Live progress and resume point; owner-waiting section | Every session start |
| `docs/OPEN_QUESTIONS.md` | Parked non-blocking questions with defaults | At gates |
| `docs/reports/` | Milestone reports | At milestone end |
| `.claude/settings.json` | Pre-approved commands so the agent isn't prompted constantly | Claude Code reads it automatically |
| `.claude/agents/spec-reviewer.md` | Subagent that reviews every step's diff before commit | Every step |
| `docs/decisions/` | Architecture Decision Records (ADRs) Claude Code writes when it deviates from the spec | Created as needed |

## How to use with Claude Code (v6: autonomous)

Start Claude Code in the repo and paste:

> Read CLAUDE.md, docs/AGENT_WORKFLOW.md and docs/STATUS.md. The owner has approved your M0 plan; the decisions are in docs/decisions/0002-m0-planning-decisions.md and docs/decisions/0003-ai-provider-and-settings-in-app-config.md. Work autonomously from M0 onward, following AGENT_WORKFLOW.md. Stop only at a human gate.

To resume after any break, say: "Resume per docs/STATUS.md."

## How to use with Claude Code (v5, step-by-step — superseded)

1. Put `CLAUDE.md` at the repo root and the `docs/` folder beside it.
2. Give Claude Code one milestone at a time: *"Implement docs/milestones/M0.md. Read CLAUDE.md and docs/ARCHITECTURE.md first."*
3. A milestone is done only when its acceptance tests pass and `docs/EVALUATION.md` metrics are recorded where applicable.
4. If implementation evidence contradicts the spec, Claude Code writes an ADR in `docs/decisions/` and updates the affected doc rather than silently diverging.

## Decisions made since v6

- **AI settings are app configuration (ADR 0003).** The AI provider and model per task, the API key and the eval corpus path are stored in MosAic's configuration, not shell env vars. Keys go to the OS keyring; the owner enters values with `mosaic config` when the agent first needs them. Anthropic is the default provider; others can be selected.
- **Git:** `Samples/` and `Other/` are gitignored.

## Decisions made since v5

- **Development is autonomous.** The agent plans, implements, tests, self-reviews (`spec-reviewer` subagent), commits, and continues across milestones. It stops only at human gates (G1–G7 in `docs/AGENT_WORKFLOW.md`). Quality reviews happen only at the end of M0, M2 and M4.
- **Owner decisions on the M0 planning pass (A–R)** are recorded in ADR 0002 and folded into M0, ARCHITECTURE, EVALUATION, API_MAP and FUTURE_APPENDIX. Highlights:
  - LGPL FFmpeg built for dev
  - frame-barcode accuracy tests
  - fake AI adapter for CI
  - Dubai target 75 s, Airshow 3 min
  - draft expectations that don't block until the owner reviews them
  - a control DB in M0
  - descriptor at the folder root
- **Budgets:** $5 per eval run, $25 per milestone. Haiku 4.5 for vision; Sonnet 5.5 for planning and selection (Anthropic defaults; see ADR 0003).
- **Licensing allow-list** extended: HPND (Pillow), WTFPL (zimg), SIL OFL (fonts), public domain / CC0; CC-BY for test fixtures only.

## Decisions made since v4

- **Name:** the app is **MosAic**. The workspace folder is `MosAic/`, the project descriptor is `.mosaic-project.json`, and the CLI is `mosaic`.
- **UI approved:**
  - canvas: https://claude.ai/artifact/K5A2TuoKdXjcnoSrFxXNSc
  - design system: https://claude.ai/artifact/2tiJkvRfQE5rWvdsQ3sb55
- **Look:**
  - dark-first, with a golden-hour amber accent
  - Geist / Geist Mono, bundled
  - logo direction A (contact-sheet grid with a merged amber tile)
- **AI-vs-you rule:** an outlined chip with an "AI" tag means the AI decided; a filled chip with a blue person badge means you decided. Locks and include rules are always blue.
- **Data model additions:** labeling questions, `person_link` (no face recognition), findings with apply/ignore state, saved presets, local model registry.
- **API map:** derived from the screens, so the backend in M0/M1 exposes shapes the UI needs.
- **Storybook and visual regression** added to M2 acceptance.

## Decisions made since v3

- **Product posture:** personal tool first, designed to become commercial. Dependency licensing is enforced from day one.
- **Deployments:** server (Linux Docker) and Mac desktop (Tauri) both in v1, sharing one backend. Windows desktop follows once the Mac build is stable.
- **Job system:** database-backed DAG queue with local worker processes. Celery/Redis removed from v1.
- **Storage:** automatic placement policy (in-folder vs split vs external) because footage lives on local, NAS and cloud-synced storage.
- **Sequencing:** walking skeleton (M0) produces a real edit from real footage before UI and packaging.
- **Transcription** moved into M0.
- **AI never computes timeline positions;** a deterministic solver and cut refiner do.
- **Cameras:** iPhone, GoPro, Insta360, Nikon (plus DJI) with a camera-profile plug-in model; any length and type is the commercial target.
- **Photos** are first-class assets usable in edits.
- **Trip context** is optional and can be added at any time.
- **Analysis modes:** Quick / Balanced / Thorough / Custom with progressive deepening.
- **OTIO/FCPXML export** moved to a later milestone; the canonical timeline stays OTIO-mappable.
