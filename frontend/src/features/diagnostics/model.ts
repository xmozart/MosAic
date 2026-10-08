/** `GET /diagnostics/tasks` rows and `/diagnostics/tasks/{tid}` (ADR 0051). */
export type TaskStatus = "pending" | "ready" | "leased" | "done" | "failed" | "skipped" | "cancelled";

export interface TaskRow {
  task_id: number;
  job_id: number;
  job_kind: string | null;
  project_id: string;
  kind: string;
  stage: string;
  input: string | null;
  status: TaskStatus;
  attempts: number;
  max_attempts: number;
  duration_ms: number | null;
  created_at: string;
  finished_at: string | null;
  tool: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
}

export interface TaskDetail extends TaskRow {
  error: string | null;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  events: { event: string; worker_id: string | null; detail: string | null; at: string }[];
  started_at: string | null;
  worker: string | null;
  can_retry: boolean;
  can_skip: boolean;
}

/** States that still change: the list and a task's detail poll while one shows. */
export const LIVE: ReadonlySet<TaskStatus> = new Set(["pending", "ready", "leased"]);

/** S23's status filter: plain words over the queue's states. */
export const FILTERS: { value: "all" | TaskStatus; label: string }[] = [
  { value: "all", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "leased", label: "Running" },
  { value: "ready", label: "Waiting" },
  { value: "done", label: "Done" },
];

export const STATUS_WORDS: Record<TaskStatus, string> = {
  pending: "pending",
  ready: "waiting",
  leased: "running",
  done: "done",
  failed: "failed",
  skipped: "skipped",
  cancelled: "cancelled",
};

export const STATUS_TONE: Record<TaskStatus, string> = {
  pending: "text-text-faint",
  ready: "text-text-faint",
  leased: "text-accent",
  done: "text-use",
  failed: "text-reject",
  skipped: "text-text-muted",
  cancelled: "text-text-muted",
};

/** "4.2 s", "38.1 s", "2 m 05 s"; "—" until it ran. */
export function duration(ms: number | null): string {
  if (ms == null) return "—";
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1)} s`;
  const whole = Math.round(ms / 1000); // whole seconds first, so no "1 m 60 s"
  return `${Math.floor(whole / 60)} m ${String(whole % 60).padStart(2, "0")} s`;
}

/** "1,840 / 610 tok" (in / out) for AI tasks. */
export function tokens(r: Pick<TaskRow, "tokens_in" | "tokens_out">): string {
  if (r.tokens_in == null && r.tokens_out == null) return "—";
  return `${(r.tokens_in ?? 0).toLocaleString("en-US")} / ${(r.tokens_out ?? 0).toLocaleString("en-US")} tok`;
}

export function cost(usd: number | null): string {
  if (usd == null) return "—";
  if (usd === 0) return "$0";
  return usd < 0.01 ? `$${usd.toFixed(3)}` : `$${usd.toFixed(2)}`;
}

/** "14:02:11" from an ISO time (display). */
export function clockTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
}
