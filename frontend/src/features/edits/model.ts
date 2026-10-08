import type { WizardStep } from "@/components/edit/Wizard";
import { formatCost, formatWall } from "@/lib/estimate";
import { formatOpened } from "@/lib/format";
import { formatClock, parseRational } from "@/lib/time";

/** The edit request (backend `EditRequest`; PRODUCT.md §4, ADR 0046). */
export type Aspect = "16:9" | "9:16" | "4:5" | "1:1" | "2.39:1";
export type Resolution = "720p" | "1080p" | "1440p" | "4k";
export type Chronology = "strict" | "mostly" | "thematic" | "story";
export type Pace = "very_slow" | "slow" | "balanced" | "energetic" | "fast" | "very_fast";

export interface EditRequest {
  duration_s: number;
  story: string;
  chronology: Chronology;
  pace: Pace;
  tolerance_pct: number;
  instructions: string;
  fps: string | null;
  aspect: Aspect;
  resolution: Resolution;
}

export const DEFAULT_TOLERANCE = 5; // percent; "Strict length" sets 0

export const DEFAULT_REQUEST: EditRequest = {
  duration_s: 180,
  story: "cinematic_journey",
  chronology: "mostly",
  pace: "balanced",
  tolerance_pct: DEFAULT_TOLERANCE,
  instructions: "",
  fps: null,
  aspect: "16:9",
  resolution: "1080p",
};

export const MAX_SECONDS = 4 * 3600;
export const MIN_SECONDS = 5;
export const MAX_INSTRUCTIONS = 2000;

/** S14 step 1 duration chips, in seconds. */
export const DURATIONS = [15, 30, 60, 90, 120, 180, 300, 600, 900, 1200] as const;

export const ASPECTS: { value: Aspect; label: string; w: number; h: number }[] = [
  { value: "16:9", label: "16:9", w: 64, h: 36 },
  { value: "9:16", label: "9:16", w: 28, h: 50 },
  { value: "4:5", label: "4:5", w: 40, h: 50 },
  { value: "1:1", label: "1:1", w: 44, h: 44 },
  { value: "2.39:1", label: "2.39:1", w: 70, h: 29 },
];

export const RESOLUTIONS: { value: Resolution; label: string }[] = [
  { value: "720p", label: "720p" },
  { value: "1080p", label: "1080p" },
  { value: "1440p", label: "1440p" },
  { value: "4k", label: "4K" },
];

/** Frame rates offered under More options; `null` follows the footage. */
export const FRAME_RATES: { value: string | null; label: string }[] = [
  { value: null, label: "Native" },
  { value: "24000/1001", label: "23.976 fps" },
  { value: "24", label: "24 fps" },
  { value: "25", label: "25 fps" },
  { value: "30000/1001", label: "29.97 fps" },
  { value: "30", label: "30 fps" },
  { value: "50", label: "50 fps" },
  { value: "60000/1001", label: "59.94 fps" },
  { value: "60", label: "60 fps" },
];

export const CHRONOLOGY: { value: Chronology; label: string }[] = [
  { value: "strict", label: "Strict" },
  { value: "mostly", label: "Mostly chronological" },
  { value: "thematic", label: "Thematic" },
  { value: "story", label: "Story-driven" },
];

const PACE_WORDS: Record<Pace, string> = {
  very_slow: "Very slow",
  slow: "Slow",
  balanced: "Balanced",
  energetic: "Energetic",
  fast: "Fast",
  very_fast: "Very fast",
};
/** Preferred seconds per shot: the middle value of `PACE_SECONDS` in
 * backend/mosaic/editing/request.py (display only; keep the two in step). */
const PACE_SHOT: Record<Pace, number> = { very_slow: 7, slow: 5.5, balanced: 3.5, energetic: 2.5, fast: 1.8, very_fast: 1.2 };

/** Short words for edit names: "Costa Rica — 5 min cinematic". */
const STORY_SHORT: Record<string, string> = {
  chronological_diary: "diary",
  cinematic_journey: "cinematic",
  adventure_highlights: "highlights",
  family_memories: "family memories",
  people_first: "people",
  nature: "nature",
  wildlife: "wildlife",
  food_culture: "food and culture",
  city: "city",
  road_trip: "road trip",
  relaxed: "relaxed",
  high_energy_montage: "montage",
  documentary: "documentary",
  funny_moments: "funny moments",
  drone_showcase: "drone",
  event_recap: "recap",
};

/** `GET /projects/{pid}/presets` (ADR 0047). */
export interface Preset {
  id: string;
  label: string;
  description: string;
  featured: boolean;
}

/** `POST /edits/estimate` (ADR 0047). */
export interface EditEstimate {
  candidates: number;
  target: { frames: number; rate: string };
  usable_seconds: number;
  enough_footage: boolean;
  reuses_plan: boolean;
  cost_usd: [number, number] | null;
  wall_seconds: [number, number];
  preliminary: boolean;
  analysis_pct: number | null;
}

export type EditStatus = "generating" | "failed" | "new" | "ready" | "rendering" | "preview" | "final";

/** `GET /projects/{pid}/edits` item (ADR 0047). */
export interface EditCardData {
  edit_id: string;
  display_id: string;
  name: string | null;
  title: string | null;
  request: Partial<EditRequest>;
  aspect: Aspect;
  resolution: Resolution;
  latest_version: number | null;
  versions: number;
  duration: { frames: number; rate: string } | null;
  cover_sample_id: number | null;
  status: EditStatus;
  pct: number | null;
  job_id: number | null;
  error: string | null;
  preliminary: boolean;
  created_at: string;
}

/** "15 s", "90 s", "2 min", "5 min", "1 h 30 min". */
export function lengthLabel(seconds: number): string {
  if (seconds < 120) return `${seconds} s`;
  if (seconds % 60 !== 0) return formatClock(seconds);
  const m = seconds / 60;
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

/** "5-minute", "60-second", "1:30" — the adjective form for the summary line. */
function lengthAdjective(seconds: number): string {
  if (seconds % 60 === 0 && seconds >= 120 && seconds < 3600) return `${seconds / 60}-minute`;
  if (seconds < 120) return `${seconds}-second`;
  return formatClock(seconds);
}

export function frameRateLabel(fps: string | null): string {
  return FRAME_RATES.find((f) => f.value === fps)?.label ?? `${fpsNumber(fps ?? "30")} fps`;
}

function fpsNumber(rate: string): string {
  const [n, d] = parseRational(rate);
  return String(Math.round((n / d) * 1000) / 1000);
}

export function resolutionLabel(r: Resolution): string {
  return RESOLUTIONS.find((x) => x.value === r)?.label ?? r;
}

export function formatLabel(aspect: Aspect, resolution: Resolution): string {
  return `${aspect} · ${resolutionLabel(resolution)}`;
}

/** ± seconds around the target, or 0 when strict (the backend rounds frames, this is display). */
export function toleranceSeconds(req: Pick<EditRequest, "duration_s" | "tolerance_pct">): number {
  return Math.round((req.duration_s * req.tolerance_pct) / 100);
}

/** S14's summary panel lines, from the request alone (S14 acceptance: single source). */
export function summaryLines(req: EditRequest, presets: Preset[]): string[] {
  const story = presets.find((p) => p.id === req.story)?.label ?? req.story.replace(/_/g, " ");
  const tol = toleranceSeconds(req);
  const lines = [
    `${lengthAdjective(req.duration_s)} ${story.toLowerCase()}`,
    `${formatLabel(req.aspect, req.resolution)} · ${req.fps ? frameRateLabel(req.fps) : "native frame rate"}`,
    CHRONOLOGY.find((c) => c.value === req.chronology)?.label ?? req.chronology,
    `${PACE_WORDS[req.pace]} pace · about ${PACE_SHOT[req.pace]} s per shot`,
    req.tolerance_pct === 0 ? "Strict length" : `Length within ±${tol} s`,
  ];
  const notes = req.instructions.trim();
  if (notes) lines.push(`Notes: ${notes.length > 80 ? `${notes.slice(0, 79)}…` : notes}`);
  return lines;
}

/** The edit's default name: "Costa Rica — 5 min cinematic" (the trip name is the owner's). */
export function defaultName(trip: string, req: Pick<EditRequest, "duration_s" | "story">): string {
  return `${trip} — ${lengthLabel(req.duration_s)} ${STORY_SHORT[req.story] ?? req.story.replace(/_/g, " ")}`;
}

/** "About 3 min · ~$0.40"; "A few seconds · no AI cost" when the plan is reused. */
export function estimateText(e: EditEstimate): string {
  if (e.reuses_plan) return "A few seconds · no AI cost";
  const cost = formatCost(e.cost_usd);
  return `${formatWall(e.wall_seconds)} · ${cost.startsWith("$") ? `~${cost}` : cost}`;
}

export function cardName(c: EditCardData): string {
  return c.name ?? c.title ?? c.display_id;
}

/** "5:02" from the edit's exact length (frames at its rate). */
export function cardDuration(c: EditCardData): string | null {
  if (!c.duration) return null;
  const [n, d] = parseRational(c.duration.rate);
  return formatClock((c.duration.frames * d) / n);
}

export type StatusTone = "done" | "ready" | "busy" | "warn" | "failed" | "idle";

export function statusWords(c: Pick<EditCardData, "status" | "pct" | "preliminary">): { text: string; tone: StatusTone } {
  if (c.preliminary && (c.status === "ready" || c.status === "preview")) return { text: "Preliminary", tone: "warn" };
  switch (c.status) {
    case "generating":
      return { text: `Generating… ${c.pct ?? 0}%`, tone: "busy" };
    case "failed":
      return { text: "Couldn't create", tone: "failed" };
    case "new":
      return { text: "Waiting to start", tone: "idle" };
    case "rendering":
      return { text: "Rendering preview…", tone: "busy" };
    case "preview":
      return { text: "Preview ready", tone: "ready" };
    case "final":
      return { text: "Final rendered", tone: "done" };
    default:
      return { text: "Ready", tone: "idle" };
  }
}

/** "Created Today 14:20", "Created Jul 25". */
export function createdText(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const day = formatOpened(iso, now);
  const recent = day === "Today" || day === "Yesterday";
  const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `Created ${day}${recent ? ` ${time}` : ""}`;
}

/** A request from an existing edit's, for S13's "Start from" chips (ADR 0048). */
export function requestFrom(base: Partial<EditRequest> | undefined, patch: Partial<EditRequest> = {}): EditRequest {
  const merged = { ...DEFAULT_REQUEST, ...(base ?? {}), ...patch };
  return { ...merged, duration_s: clampSeconds(merged.duration_s) };
}

export function clampSeconds(s: number): number {
  return Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, Math.round(s)));
}

/** Another length for "Duplicate … as …": long edits get a short cut, short ones a longer one. */
export function otherLength(seconds: number): number {
  return seconds >= 120 ? 90 : 180;
}

/** M2 builds steps 1, 2 and 6; the others show and wait for M4 (ADR 0048). */
export const STEPS: WizardStep[] = [
  { id: 1, label: "Length & format" },
  { id: 2, label: "Story" },
  { id: 3, label: "What to feature", later: true },
  { id: 4, label: "Style", later: true },
  { id: 5, label: "Sound", later: true },
  { id: 6, label: "Anything else?" },
];

/** Idea chips: generic on purpose, never a place or a person (invariant 16). */
export const IDEAS = ["Avoid long driving clips.", "End on the best sunset.", "Include funny reactions.", "Open with an aerial shot."];

export interface StartFrom {
  kind: "duplicate" | "vertical";
  from: EditCardData;
  label: string;
}

/** S13's "Start from" chips: duplicate the newest edit as another length, and a vertical
 * version of the newest landscape edit (ADR 0048; saved presets come with M4). */
export function startFromChips(items: EditCardData[]): StartFrom[] {
  const made = items.filter((e) => e.latest_version !== null);
  const out: StartFrom[] = [];
  const newest = made[0];
  if (newest?.request.duration_s) {
    out.push({ kind: "duplicate", from: newest, label: `Duplicate “${cardName(newest)}” as ${lengthLabel(otherLength(newest.request.duration_s))}` });
  }
  const wide = made.find((e) => e.aspect !== "9:16");
  if (wide) out.push({ kind: "vertical", from: wide, label: `Vertical version of “${cardName(wide)}”` });
  return out;
}

export function isAspect(v: string | null): v is Aspect {
  return ASPECTS.some((a) => a.value === v);
}

export function coverShape(a: Aspect): "landscape" | "9:16" | "4:5" | "1:1" {
  return a === "9:16" || a === "4:5" || a === "1:1" ? a : "landscape";
}
