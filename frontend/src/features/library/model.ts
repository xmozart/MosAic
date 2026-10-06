import type { CameraKind, DecidedBy, Disposition } from "@/lib/domain";
import { formatDay } from "@/lib/format";
import { formatClock, seconds, tenths, type SourceTime } from "@/lib/time";

/** One clip of `GET /projects/{pid}/library` (API_MAP; ADR 0031, 0042, 0044). */
export interface LibraryItem {
  asset_id: number;
  kind: "video" | "photo" | "live_photo";
  status: string;
  name: string | null;
  group: string;
  capture_time: string | null;
  duration: SourceTime | null;
  segments: number;
  status_shown: Disposition | null;
  decided_by: DecidedBy | null;
  decision: ClipDecision;
  sample_id: number | null;
  caption: string | null;
  shot_type: string | null;
  has_speech: boolean;
  similar_count: number;
  offline: boolean;
  camera: { label: string; kind: CameraKind };
}

export interface ClipDecision {
  disposition: Disposition | null;
  stars: number | null;
  include: "always" | "never" | null;
  note: string | null;
  live_motion: boolean | null;
  tags: string[];
}

export interface LibraryGroup {
  key: string;
  label: string;
  count: number;
  clips: number;
  photos: number;
  footage_seconds: number;
  day?: number | null;
  date?: string | null;
  place?: string | null;
}

export interface LibraryPage {
  items: LibraryItem[];
  next_cursor: string | null;
  groups: LibraryGroup[] | null;
  rejected_hidden: number | null;
}

export type Grouping = "day" | "camera" | "similar";
export type StatusFilter = "USE" | "MAYBE" | "REJECT" | "none";

export interface Filters {
  status?: StatusFilter;
  min_stars?: number;
  camera?: number;
  day?: string;
  tag?: string;
  include?: "always" | "never";
  kind?: "video" | "photo";
  shot_type?: ShotType;
  has_speech?: boolean;
}

export type ShotType =
  | "establishing_wide"
  | "wide"
  | "medium"
  | "close_up"
  | "detail"
  | "aerial"
  | "pov"
  | "selfie"
  | "other";

export const SHOT_TYPES: { value: ShotType; label: string }[] = [
  { value: "establishing_wide", label: "Establishing" },
  { value: "wide", label: "Wide" },
  { value: "medium", label: "Medium" },
  { value: "close_up", label: "Close-up" },
  { value: "detail", label: "Detail" },
  { value: "aerial", label: "Aerial" },
  { value: "pov", label: "Point of view" },
  { value: "selfie", label: "Selfie" },
  { value: "other", label: "Other" },
];

export function activeFilters(f: Filters): number {
  return Object.values(f).filter((v) => v !== undefined).length;
}

/** The change a decision key or the BulkBar makes (PATCH / bulk body; null resets). */
export type DecisionChange = Partial<{
  disposition: Disposition | null;
  stars: number | null;
  include: "always" | "never" | null;
  note: string | null;
  live_motion: boolean | null;
  tags: string[];
  add_tags: string[];
  remove_tags: string[];
}>;

/** What a tile shows right after an owner decision, before the server answers (S10:
 * "a user decision renders as user style immediately"). Mirrors ADR 0042's precedence. */
export function optimistic(item: LibraryItem, change: DecisionChange): LibraryItem {
  const decision: ClipDecision = { ...item.decision };
  for (const k of ["disposition", "stars", "include", "note", "live_motion"] as const) {
    if (k in change) (decision as unknown as Record<string, unknown>)[k] = change[k] ?? null;
  }
  if (change.tags) decision.tags = [...change.tags].sort();
  if (change.add_tags) decision.tags = [...new Set([...decision.tags, ...change.add_tags])].sort();
  if (change.remove_tags) decision.tags = decision.tags.filter((t) => !change.remove_tags!.includes(t));
  const rule: Disposition | null =
    decision.include === "never" ? "REJECT" : decision.include === "always" ? "USE" : decision.disposition;
  const touched = "disposition" in change || "include" in change;
  if (touched && rule) return { ...item, decision, status_shown: rule, decided_by: "user" };
  return { ...item, decision };
}

/** "0:48", "4:02", "1:02:10" from exact source time (display only). */
export function clipLength(d: SourceTime | null): string | undefined {
  return d ? formatClock(seconds(d)) : undefined;
}

/** `GET /projects/{pid}/clips/{aid}` (API_MAP; ADR 0043). */
export interface ClipDetail {
  asset_id: number;
  kind: "video" | "photo" | "live_photo" | "unsupported";
  status: string;
  name: string | null;
  files: number;
  reason: string | null;
  fix: string | null;
  camera: string;
  capture_time: string | null;
  duration: SourceTime | null;
  rate: string | null;
  proxy_rate: string | null; // the served proxy's frame rate: the player steps by it
  width: number | null;
  height: number | null;
  badges: string[];
  analysis_only: boolean;
  position: { day: number | null; date: string | null; index: number; count: number; prev: number | null; next: number | null } | null;
  status_shown: Disposition | null;
  decided_by: DecidedBy | null;
  ai_status: Disposition | null;
  decision: ClipDecision;
  why: { description: string | null; reasons: string[] };
  moments: {
    segment_id: number;
    start: SourceTime;
    end: SourceTime;
    usable_start: SourceTime;
    usable_end: SourceTime;
    status: Disposition | null;
    decided_by: "user" | "clip" | "ai" | null;
    ai_status: Disposition | null;
    description: string | null;
    interest: string | null;
    reasons: string[];
    has_speech: boolean;
    sample_id: number | null;
  }[];
  quality: Record<"sharpness" | "steadiness" | "exposure" | "audio", "Poor" | "Fair" | "Good" | "Excellent" | null>;
  transcript: { segments: number; language: string | null };
  used_in: { edit_id: string; name: string; version: number }[];
  similar: { asset_id: number; sample_id: number | null }[];
  burst: { items: { asset_id: number; sample_id: number | null; best: boolean }[] } | null;
}

/** The AI-vs-you line (S10, S11): what the analysis suggested beside what the owner set. */
export function aiVersusYou(c: Pick<ClipDetail, "ai_status" | "decision">): string {
  const parts = [c.ai_status ? `AI suggested ${c.ai_status}` : "Not analyzed yet"];
  const d = c.decision;
  if (d.include === "never") parts.push("You: never include");
  else if (d.include === "always") parts.push("You: always include");
  if (d.disposition) parts.push(`You: ${d.disposition}`);
  if (d.stars) parts.push(`You rated ${"★".repeat(d.stars)}`);
  return parts.join(" · ");
}

/** The inspector's copy of a clip after an owner decision, before the server answers. */
export function optimisticClip(c: ClipDetail, change: DecisionChange): ClipDetail {
  const tile = optimistic(
    { decision: c.decision, status_shown: c.status_shown, decided_by: c.decided_by } as LibraryItem,
    change,
  );
  return { ...c, decision: tile.decision, status_shown: tile.status_shown, decided_by: tile.decided_by };
}

/** "0:02.9": a moment's time to a tenth of a second (display). */
export const clock = tenths;

/** "iPhone 16 Pro · Jul 16, 07:52 · Day 3 · 0:07". */
export function factsLine(c: ClipDetail): string {
  return [
    c.camera,
    c.capture_time ? `${formatDay(c.capture_time.slice(0, 10))}, ${c.capture_time.slice(11, 16)}` : null,
    c.position?.day ? `Day ${c.position.day}` : null,
    clipLength(c.duration),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The clip's usable range: from its first non-rejected moment's usable start to the last
 * one's usable end (the player's green band). */
export function usableRange(c: Pick<ClipDetail, "moments">): { start: SourceTime; end: SourceTime } | undefined {
  const kept = c.moments.filter((m) => m.status !== "REJECT");
  const list = kept.length ? kept : c.moments;
  const first = list[0]?.usable_start;
  const last = list.at(-1)?.usable_end;
  return first && last ? { start: first, end: last } : undefined;
}
