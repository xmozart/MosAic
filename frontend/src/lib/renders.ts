/** A render row (`GET /projects/{pid}/renders`, and a version's `renders`; ADR 0047). */
export type RenderStatus = "queued" | "rendering" | "paused" | "done" | "failed" | "cancelled" | "deleted" | "missing";

export interface RenderRow {
  render_id: number;
  edit_id: string | null;
  edit_name: string | null;
  display_id: string;
  version: number;
  cover_sample_id: number | null;
  kind: "preview" | "final";
  label: string;
  width: number;
  height: number;
  status: RenderStatus;
  pct: number | null;
  error: string | null;
  job_id: number | null;
  size_bytes: number | null;
  seconds: number | null;
  file: string | null;
  created_at: string;
  finished_at: string | null;
}

export const ACTIVE: ReadonlySet<RenderStatus> = new Set(["queued", "rendering", "paused"]);

/** The file of a render: inline for the player, or as a download. */
export function renderFile(pid: string, rid: number, download = false): string {
  return `/api/projects/${pid}/renders/${rid}/file${download ? "?download=true" : ""}`;
}

/** The newest render of ``kind`` in ``rows`` (newest first) that is not cancelled. */
export function latest(rows: RenderRow[], kind: RenderRow["kind"]): RenderRow | undefined {
  return rows.find((r) => r.kind === kind && r.status !== "cancelled" && r.status !== "deleted");
}

/** S20's status words: "Queued", "Rendering 58%", "Done", "Failed"… */
export function renderStatusText(r: Pick<RenderRow, "status" | "pct">): string {
  switch (r.status) {
    case "queued":
      return "Queued";
    case "rendering":
      return `Rendering ${r.pct ?? 0}%`;
    case "paused":
      return "Paused";
    case "done":
      return "Done";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    case "deleted":
      return "File deleted";
    default:
      return "File missing";
  }
}

/** "40 s", "9 m 12 s", "1 h 05 m": how long a render took (display). */
export function renderTime(seconds: number | null): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} m ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} m`;
}
