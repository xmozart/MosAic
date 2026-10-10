/** `GET /api/models/local` rows (ADR 0058). */
export interface ModelRow {
  name: string;
  label: string;
  capability: "transcriber" | "embedder";
  provider: string;
  model: string;
  bytes: number;
  downloaded_bytes: number;
  installed: boolean;
  needed: boolean;
  job: { job_id: number; state: string; pct: number } | null;
}

/** The setting that records a finished first run (desktop; ADR 0059). */
export const FIRST_RUN_DONE = "app.first_run_done";
