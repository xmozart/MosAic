export type Preset = "quick" | "balanced" | "thorough";

export const MODES: { id: Preset; title: string; description: string }[] = [
  { id: "quick", title: "Quick", description: "See results fast. Good for short trips or a first look." },
  { id: "balanced", title: "Balanced", description: "Great edits for most trips." },
  { id: "thorough", title: "Thorough", description: "Best shot selection and cut points. Deep review of your best clips." },
];

/** One project setting as `/projects/{pid}/settings` reports it (ADR 0041). */
export interface Setting {
  value: unknown;
  source: "project" | "user" | "default" | "mode";
}
export type Settings = Record<string, Setting>;

export const FROM: Record<Setting["source"], string> = {
  project: "This project",
  user: "Your preference",
  default: "Default",
  mode: "From the mode",
};

/** Scene sensitivity is the longest a shot runs before it is split (ADR 0041). */
export const SENSITIVITY = { low: "120", medium: "60", high: "30" } as const;

/** `GET /projects/{pid}/analysis/progress` (API_MAP; ADR 0041). */
export interface Progress {
  job_id: number;
  kind: string;
  mode: string | null;
  deepen: { target: string | null; days: number[]; segment_ids: number[] } | null;
  steps: {
    key: string;
    label: string;
    state: "pending" | "running" | "done" | "failed" | "paused";
    done: number;
    failed: number;
    total: number;
    pct: number;
    note: string | null;
  }[];
  ready_to_browse: boolean;
  live: { mosaic_id: number; tiles: number; cols: number; rows: number; description: string | null; file: string | null; day: number | null } | null;
  failures: { count: number; items: { asset_id: number | null; file: string | null; stage: string; reason: string }[] };
  clips: { done: number; total: number };
}

/** The parts of `GET /jobs/{id}` S9 reads. */
export interface JobInfo {
  job_id: number;
  state: string; // running | paused | paused_cost_limit | done | failed | cancelled
  cost_usd: number;
  cost_limit_usd: number | null;
  progress: { pct: number; eta: { ms: number; display: string } | null } | null;
}

/** "About 58 min left", "About 1 h 05 m left" (shown only once the job has an ETA). */
export function timeLeft(ms: number): string {
  const mins = Math.max(1, Math.round(ms / 60_000));
  return mins < 60 ? `About ${mins} min left` : `About ${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, "0")} m left`;
}

