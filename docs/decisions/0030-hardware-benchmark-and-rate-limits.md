# 0030 — Hardware probe, benchmark, worker slots and AI rate limits

- Status: accepted (M1 step 12)
- Deciders: agent (autonomous; no human gate)

## Context

M1 asks for three things:
- a hardware capability probe and a benchmark that feeds estimates (ANALYSIS_MODES §4: "estimated wall time from a hardware benchmark plus footage duration");
- a worker pool with resource classes, auto-sized from the probe (ARCHITECTURE §3);
- per-provider rate limits for `ai_api` tasks (ARCHITECTURE §7; ADR 0012 deferred the token buckets to M1).

Until now, estimates used per-mode speed factors measured once on the M0 eval machine. Worker slots were `cpu = max(2, cpus // 2)` plus fixed counts for the other classes. AI calls relied on the provider SDK's 429 retries.

## Options

**Benchmark input**
1. Time a slice of the owner's own footage. This is the most realistic, but the result depends on the project: it would need per-codec bookkeeping, and it means reading originals for something other than analysis.
2. Time a generated clip. The result depends only on the machine, it is repeatable, and it can be stored once per computer.

**Where the benchmark runs**
1. Inline in the API or CLI.
2. As a job, as invariant 8 requires.

Jobs are project-scoped (`job.project_id` is required), so a system job would need a schema change and a worker path that runs without a project.

**Rate-limit scope**
1. Shared across processes through the control DB.
2. Process-wide in the worker. Only one worker process runs AI tasks (ADR 0002 K), so this is enough for now.

## Decision

**Probe** (`media/hardware.py`)
- Reads the OS, architecture, CPU model, logical, physical and Apple performance cores, memory, and the hardware H.264 encoders that actually run here (VideoToolbox, NVENC, QSV or AMF, from the encoder trial).
- Values it cannot read are `None`; probing never fails.
- A fingerprint (a hash of OS, architecture, CPU model, thread count and memory) identifies the machine for a stored benchmark.

**Benchmark** (`media/benchmark.py`, task `system.benchmark`, version `benchmark/1`)
- Generates a 4-second 3840×2160 30 fps noisy test clip with the first working H.264 encoder. The generator is the `bench_source` builder. The clip goes in `app_data/tmp` and is removed afterwards.
- Times three things:
  - the real proxy builder at 540p and 720p (with the same hardware-decode fallback as the proxy task);
  - the real per-frame visual pass, `visual.frame_pass` (extracted from `pass_a`) over the 720p proxy;
  - SigLIP image embeddings per image, when the configured embedder loads. Otherwise the estimate uses a default of 150 ms.
- Stores integer milliseconds per minute of footage in a new control-DB table, `hardware_benchmark`, keyed by fingerprint and version. A re-run replaces the row. These are measurements for display, never authoritative times (invariant 3).
- Runs as a job in a project's queue:
  - automatically as the first task of an analysis started from the CLI, API or eval when this computer has no benchmark (scanning waits for it, so the benchmark is not slowed by the analysis it measures);
  - explicitly through `mosaic hardware FOLDER --benchmark [--force]` or `POST /projects/{pid}/benchmark`.
- Its `is_done` skips it when a result for this machine exists. Analyses submitted directly through `submit_analysis` (tests, library code) do not add it.

**Estimates** (`library/estimate.py`)
- With a benchmark, local time is computed as:

  ```
  minutes × proxy_ms[mode.proxy] / min(gpu_encode slots, videos)
  + (minutes × frame_ms + samples × embed_ms) / min(cpu slots, videos)
  ```

- The existing AI-call time and the ×0.7–×1.5 spread are added as before. `basis` is `"benchmark"`.
- Without a benchmark, the M0 factors are used and `basis` is `"default"`. The CLI then suggests running the benchmark.
- Calibration check, on the eval machine (Apple M4, 10 threads, 32 GB):
  - The benchmark measured 33.4 s per minute for the 720p proxy, 12.6 s per minute for the frame pass and 145 ms per embedding.
  - With 5 CPU slots and 2 encode slots, that predicts ≈ 0.33 × footage for Balanced. The measured M0 Airshow run was 0.30 × (90 min in 27 min).
  - The unmeasured stages (audio, sample extraction, sheets) overlap with proxy encoding, so no extra overhead factor is applied.

**Worker slots** (`jobs/worker.py`)
- `cpu`: `max(2, threads // 2)`, capped at one slot per 2 GB of memory (Whisper medium or the frame pass at peak).
- `gpu_encode`: 2 with a hardware encoder, otherwise 1 (software encoding is CPU work).
- `ai_api`: 4; `io`: 2.
- Each class can be overridden with the `workers.<class>` setting (0 means auto). The worker logs its slots, and `/system/info` reports them.

**Rate limits** (`ai/ratelimit.py`)
- Each provider has one process-wide limiter with three bounds: concurrency, requests per minute and estimated tokens per minute, over a sliding 60-second window. A call larger than the whole token budget runs alone.
- `AIClient` holds a slot around `adapter.complete`. Waiting checks for task cancellation, and a cancelled wait refunds the job's cost reservation.
- Defaults:
  - `anthropic`: 50 requests per minute (the entry tier) and 4 concurrent calls. Token limits depend on the account's tier, so they are off unless set.
  - `claude-cli` and `codex-cli`: 2 concurrent calls each, since every call starts the installed app.
- Settings `ai.rate.<provider>.{requests_per_minute,tokens_per_minute,concurrency}` override the defaults.

**Budgets** (STATUS carry-forward)
- The `make eval` per-run ($5) and per-milestone ($25) budgets were already wired in M1 step 3: the job cost limit is `budget.remaining`, and the ledger holds the running total.
- This step only confirms that; nothing changes.

## Consequences

- Estimates on a measured computer reflect its speed and its worker pool. The first analysis on a new computer starts about 10–20 s later.
- A benchmark job appears in the project's job list. It writes only the control DB.
- Rate limits are per worker process. When distributed workers arrive (FUTURE_APPENDIX), the limiter's interface (`slot(provider, limit, tokens)`) can be backed by a shared store without changing callers.
- The benchmark runs while other projects' jobs may be running, which can make the numbers slower than the machine really is. `--force` measures again on an idle computer. Two analyses started together on a new computer may both measure it; the later result replaces the earlier one.
- Not measured, so they use defaults: Whisper speed (it overlaps with proxies) and photo decoding. Photo-heavy or speech-heavy trips may be under-estimated; the wall-time range absorbs part of this.
