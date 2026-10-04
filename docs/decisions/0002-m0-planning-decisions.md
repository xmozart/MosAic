# ADR 0002 — M0 planning decisions

- **Status:** accepted by the owner. These decisions are already folded into the affected docs. Item A's "`EVAL_CORPUS_DIR` is set in the owner's shell" is superseded by ADR 0003 (corpus path and AI settings live in the app configuration).
- **Context:** Claude Code's M0 planning pass raised items A–R. This ADR records the owner's decisions so they are not re-litigated. ADR 0001 is reserved for the M0 findings report.

| Item | Decision |
|---|---|
| **A. OneDrive location** | Done by the owner: the repo and corpus now live off cloud storage. `EVAL_CORPUS_DIR` is set in the owner's shell *(superseded by ADR 0003: app setting `eval.corpus_dir`)*. M0 ships the placement classifier for all classes but **refuses** every class except `local`, with a clear message; split and external modes stay in M1. |
| **B. FFmpeg** | Approved: a dev script builds an **LGPL FFmpeg** (zimg, VideoToolbox, libopenh264) and Homebrew deps are pre-authorized. Linux CI uses BtbN LGPL builds. A runtime check reads `-buildconf` and refuses GPL builds unless `allow_gpl_ffmpeg=true` (dev-only setting, never default). Encoder order: VideoToolbox → NVENC → openh264. Frame-exact tests use a lossless codec (FFV1). |
| **C. Dubai length** | Dubai target is **75 s** (60–90 s acceptable); Airshow target is **3 min**. The ">3 h trip" requirement moves to M1 (synthetic long project plus a real long trip when available). Photos stay out of M0 edits. |
| **D. expectations.yaml** | The agent creates `tests/evaluation/expectations.template.yaml` and a **draft** `expectations.yaml` per trip from the analysis, marked `draft: true`. The must-include and must-exclude metrics are reported but are **not blocking** until the owner confirms the drafts at gate G6. |
| **E. Frame-hash check** | Approved: an encode-robust **frame-index barcode** is burned into synthetic frames and decoded from rendered frames (±1 frame; nearest-PTS for VFR). |
| **F. Zero-target metrics** | Approved list: duration within tolerance, mid-word cuts, dialogue truncations, adjacent jump cuts, REJECT shots used, must-exclude violations. In M0, every jump cut and truncation counts as a violation. A dialogue truncation is an out-point inside a transcript segment that started within the event. |
| **G. Float seconds** | Approved: raw probe JSON is an artifact blob referenced by key; DB columns hold integer `start_pts` and `duration_ts`. The schema test rejects REAL columns and JSON keys with time-like names; non-time floats (LUFS, sharpness, cost) are allowed. Whisper times are converted to ticks at the module boundary. |
| **H. AI in CI** | Approved: a deterministic **fake/replay adapter** (responses keyed by request hash) behind the same interface. CI uses it with small Whisper and SigLIP models. Real calls happen only in `make eval`. |
| **I. Caching** | Approved: edit tasks sit downstream of the analysis DAG. Planner and selector outputs are cached by key, so an identical request makes zero AI calls. `--variant N` enters the key. |
| **J. Control DB** | Approved: M0 creates the control DB (own Alembic tree, app-data dir) with installation, user, project_registry, job tables and an edit-ID → project index. |
| **K. Workers** | Approved: one worker process separate from the API, with a thread per resource-class slot, all dispatch through `Executor`. The kill test uses `kill -9`. |
| **L. Descriptor** | `<root>/.mosaic-project.json` at the folder root; everything else under `<root>/MosAic/`. `ARCHITECTURE.md` §4 is corrected. |
| **M. LRF** | M0 associates and validates LRF files; only **Quick** mode (M1) uses them as proxies. M0 accepts only `--mode balanced`. Tested with synthetic LRFs. |
| **N. Photos** | Approved: MediaFile and `Asset(kind=photo)` rows at L0 with status `deferred` ("photos arrive in M1"). Not counted as unsupported. |
| **O. Defaults** | Approved: 1080p; timeline rate = dominant source rate by duration; `--fps` override; balanced pace stored in frames; portrait sources pillarboxed in M0; `render` defaults to the latest version with an optional `--version`. |
| **P. API** | Added `GET /edits/{eid}/report` to `API_MAP.md`. The M0 API binds 127.0.0.1 only, without auth, but still calls `authz.check`. |
| **Q. Docs** | Delete the root-level duplicate `README.md`/`API_MAP.md` copies if present; the canonical files are the spec-set `README.md` at root and `docs/ui/API_MAP.md`. ADR 0001 is reserved for M0 findings; other ADRs start at 0003. |
| **R. Footage properties** | Approved: add synthetic cases for full-range 8-bit (`yuvj420p`) and 10-bit HEVC at 59.94. Proxies and renders must honor color range and nearest-frame conform. |

**Dependencies.**
- Pillow (HPND / MIT-CMU), libzimg (WTFPL) and CC-BY-4.0 test fixtures are added to the allowed list in `CLAUDE.md`.
- **PyAV:** verify whether its wheels bundle LGPL-only FFmpeg.
  - If they do: allow it.
  - If not: decode audio with our own FFmpeg subprocess to a numpy array (faster-whisper accepts arrays), keep PyAV dev-only or unused, and record the choice in an ADR. Either way this is not a gate.
- **libopenh264:** logged in `FUTURE_APPENDIX.md` §5 for commercial patent review.

**Owner-supplied items, all resolved without blocking:**
- **Speech fixture:** use a short **public-domain LibriVox** or **CC-BY LibriSpeech** clip, attributed in `LICENSES.md`, instead of an owner recording.
- **Write permission:** the owner allows MosAic to write `.mosaic-project.json` and `MosAic/` into corpus trip folders.
- **Chaptered GoPro + LRF:** synthetic only; a real sample is optional, and arrives if the owner adds one.
- **Model tiers and budgets:** see `docs/AGENT_WORKFLOW.md` §4.
- **Git hosting:** local git, with `make ci` mirroring CI. A remote is optional; the owner may add one later.
