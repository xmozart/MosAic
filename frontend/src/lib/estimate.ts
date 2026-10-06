import { formatBytes } from "@/lib/format";

/** `GET /projects/{pid}/analysis/estimate` (API_MAP; ADR 0020, 0030, 0041). */
export interface Estimate {
  mode: string;
  preset?: string | null;
  scope: string;
  videos: number;
  photos: number;
  video_seconds: number;
  segments: number;
  l2_calls: number;
  l3_calls: [number, number];
  cost_usd: [number, number] | null;
  storage_bytes: number;
  wall_seconds: [number, number];
  basis: "benchmark" | "default";
  days?: number | null;
}

/** "About 35 min", "About 1 h 40 m" from a [low, high] range of seconds. */
export function formatWall([lo, hi]: [number, number]): string {
  const mins = Math.max(1, Math.round((lo + hi) / 2 / 60));
  if (mins < 60) return `About ${mins} min`;
  return `About ${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, "0")} m`;
}

/** "$0.80–1.50", "$2–4", "No AI cost", or "AI cost unknown" when a model has no price.
 * Both ends use cents when the low end is under $2, so a range reads alike. */
export function formatCost(cost: [number, number] | null): string {
  if (cost === null) return "AI cost unknown";
  const [lo, hi] = cost;
  if (hi === 0) return "No AI cost";
  const fmt = (x: number) => (lo < 2 ? x.toFixed(2) : String(Math.round(x)));
  return fmt(lo) === fmt(hi) ? `$${fmt(hi)}` : `$${fmt(lo)}–${fmt(hi)}`;
}

/** A mode card's mono line: "About 1 h 40 m · $2–4 · 18 GB". */
export function estimateLine(e: Estimate): string {
  return `${formatWall(e.wall_seconds)} · ${formatCost(e.cost_usd)} · ${formatBytes(e.storage_bytes)}`;
}
