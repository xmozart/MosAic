import type { Section } from "@/components/system/SectionNav";

/** `GET /settings`: app settings with their source (default / user). */
export type AppSettings = Record<string, { value: unknown; source: "default" | "user" }>;

export interface KeyStatus {
  configured: boolean;
  last4: string | null;
  store: "keychain" | "encrypted_file" | "environment" | "docker" | null;
  from_deployment: boolean;
}

/** `GET /providers`: the choice per task (ADR 0003, 0019). */
export type Providers = Record<
  string,
  { provider: string; model: string; mode: "cloud" | "cli" | "local"; source: "default" | "user" | "inherited"; key?: KeyStatus }
>;

/** `GET /providers/options` (ADR 0053). */
export interface ProviderOptions {
  capabilities: string[];
  providers: Record<string, { mode: "cloud" | "cli" | "local"; capabilities: string[]; models: string[]; fixed_models: boolean }>;
  presets: Record<string, Record<string, string>>;
}

export interface SystemInfo {
  mode: string;
  version: string;
  hardware: { cpu_model?: string | null; cpu_logical?: number; cpu_physical?: number | null; memory_bytes?: number | null; hw_encoders?: string[]; machine?: string };
  encoders: string[];
  ffmpeg: Record<string, unknown>;
  workers: Record<string, number>;
}

export interface MediaRoot {
  id: number;
  label: string | null;
  path: string;
  source: string;
}

export const SECTIONS: Section[] = [
  { id: "appearance", label: "Appearance" },
  { id: "analysis", label: "Analysis defaults" },
  { id: "ai", label: "AI providers" },
  { id: "processing", label: "Processing & hardware" },
  { id: "roots", label: "Media roots", tag: "Admin" },
  { id: "about", label: "About" },
];

/** Plain words for each AI task, in table order. */
export const TASKS: { id: string; label: string }[] = [
  { id: "vision", label: "Understanding scenes" },
  { id: "reviewer", label: "Deep review (Thorough)" },
  { id: "planner", label: "Story planning" },
  { id: "selector", label: "Shot selection" },
  { id: "critic", label: "Checking the edit" },
  { id: "summarizer", label: "Day and trip summaries" },
  { id: "transcriber", label: "Speech" },
  { id: "embedder", label: "Search" },
];

export const PROVIDER_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  "claude-cli": "Claude app",
  "codex-cli": "Codex app",
  "faster-whisper": "Whisper (local)",
  "siglip-onnx": "SigLIP (local)",
};

export const MODE_LABEL: Record<string, string> = { cloud: "Cloud", cli: "Installed app", local: "On this computer" };

const STORE: Record<string, string> = {
  keychain: "Stored in the system keychain",
  encrypted_file: "Stored encrypted on this server",
  environment: "Provided by the server's environment",
  docker: "Provided as a Docker secret",
};

export function storeText(k: KeyStatus | undefined): string | undefined {
  if (!k?.configured || !k.store) return undefined;
  return STORE[k.store];
}

/** One key card per cloud provider some task uses (S22). */
export function keyProviders(p: Providers): { provider: string; key: KeyStatus | undefined }[] {
  const seen = new Map<string, KeyStatus | undefined>();
  for (const t of Object.values(p)) if (t.mode === "cloud" && !seen.has(t.provider)) seen.set(t.provider, t.key);
  return [...seen].map(([provider, key]) => ({ provider, key }));
}

export function sourceWords(s: string): string {
  return s === "user" ? "your preference" : s === "inherited" ? "your provider choice" : "default";
}
