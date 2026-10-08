import type { AppSettings, MediaRoot, ProviderOptions, Providers, SystemInfo } from "./model";

export const SETTINGS: AppSettings = {
  "analysis.mode": { value: "balanced", source: "default" },
  "ai.budget.per_job_usd": { value: 10, source: "user" },
  "ai.local_only": { value: false, source: "default" },
  "ai.send_gps": { value: false, source: "default" },
  "workers.cpu": { value: 0, source: "default" },
};

const KEY = { configured: true, last4: "7F3A", store: "keychain" as const, from_deployment: false };

export const PROVIDERS: Providers = {
  vision: { provider: "anthropic", model: "claude-haiku-4-5", mode: "cloud", source: "default", key: KEY },
  planner: { provider: "anthropic", model: "claude-sonnet-5-5", mode: "cloud", source: "default", key: KEY },
  selector: { provider: "anthropic", model: "claude-sonnet-5-5", mode: "cloud", source: "default", key: KEY },
  critic: { provider: "anthropic", model: "claude-sonnet-5-5", mode: "cloud", source: "default", key: KEY },
  reviewer: { provider: "anthropic", model: "claude-sonnet-5-5", mode: "cloud", source: "default", key: KEY },
  summarizer: { provider: "anthropic", model: "claude-haiku-4-5", mode: "cloud", source: "default", key: KEY },
  transcriber: { provider: "faster-whisper", model: "medium", mode: "local", source: "user" },
  embedder: { provider: "siglip-onnx", model: "base", mode: "local", source: "default" },
};

export const NO_KEY: Providers = Object.fromEntries(
  Object.entries(PROVIDERS).map(([k, v]) => [k, v.key ? { ...v, key: { configured: false, last4: null, store: null, from_deployment: false } } : v]),
);

const CLOUD = ["vision", "planner", "selector", "critic", "reviewer", "summarizer"];
export const OPTIONS: ProviderOptions = {
  capabilities: [...CLOUD, "transcriber", "embedder"],
  providers: {
    anthropic: { mode: "cloud", capabilities: CLOUD, models: ["claude-haiku-4-5", "claude-opus-5-5", "claude-sonnet-5-5"], fixed_models: false },
    "claude-cli": { mode: "cli", capabilities: CLOUD, models: ["claude-haiku-4-5", "claude-sonnet-5-5"], fixed_models: false },
    "codex-cli": { mode: "cli", capabilities: CLOUD, models: ["gpt-5.5"], fixed_models: false },
    "faster-whisper": { mode: "local", capabilities: ["transcriber"], models: ["small", "medium", "large-v3"], fixed_models: true },
    "siglip-onnx": { mode: "local", capabilities: ["embedder"], models: ["base", "quantized"], fixed_models: true },
  },
  presets: {
    anthropic: { vision: "claude-haiku-4-5", planner: "claude-sonnet-5-5", selector: "claude-sonnet-5-5", critic: "claude-sonnet-5-5", reviewer: "claude-sonnet-5-5", summarizer: "claude-haiku-4-5" },
    "claude-cli": { vision: "claude-haiku-4-5", planner: "claude-sonnet-5-5", selector: "claude-sonnet-5-5", critic: "claude-sonnet-5-5", reviewer: "claude-sonnet-5-5", summarizer: "claude-haiku-4-5" },
    "codex-cli": { vision: "gpt-5.5", planner: "gpt-5.5", selector: "gpt-5.5", critic: "gpt-5.5", reviewer: "gpt-5.5", summarizer: "gpt-5.5" },
  },
};

export const SYSTEM: SystemInfo = {
  mode: "desktop",
  version: "0.2.0",
  hardware: { cpu_model: "Apple M3 Max", cpu_logical: 16, memory_bytes: 64_000_000_000, hw_encoders: ["h264_videotoolbox", "hevc_videotoolbox"] },
  encoders: ["h264_videotoolbox"],
  ffmpeg: { available: true, version: "8.1.2", license: "lgpl" },
  workers: { cpu: 6, gpu_encode: 2, ai_api: 2, io: 2 },
};

export const ROOTS: MediaRoot[] = [
  { id: 1, label: "Local disk", path: "/media/travel", source: "env" },
  { id: 2, label: "NAS · SMB", path: "/mnt/nas/video", source: "admin" },
];
