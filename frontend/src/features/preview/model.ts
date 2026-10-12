import type { PlayerSegment } from "@/components/media/Player";
import type { EditRequest } from "@/features/edits/model";
import type { RenderRow } from "@/lib/renders";
import { formatClock, parseRational, type SourceTime } from "@/lib/time";

/** A timeline position: integer frames at the edit's rate (invariant 3). */
export interface TimelineTime {
  frames: number;
  rate: string;
}

export interface TimelineEvent {
  event_id: string;
  /** "title" for a title card (ADR 0079): no clip behind it. */
  kind?: string;
  asset_id: string | null;
  segment_id: string | null;
  beat_id: string | null;
  role: string;
  timeline_in: TimelineTime;
  timeline_out: TimelineTime;
}

export interface Beat {
  beat_id: string;
  title: string;
  intent?: string;
  share_percent?: number;
}

export interface EditFactsData {
  duration: TimelineTime | null;
  target: { frames: number | null; rate: string };
  tolerance: { frames: number | null; rate: string };
  shots: number;
  photos: number;
  beats: number;
  days_used: number;
  days_available: number;
  ai_cost_usd: number | null;
}

/** `GET /edits/{eid}` and `/versions/{v}` (ADR 0047, 0049). */
export interface EditVersionData {
  edit_id: string;
  display_id: string;
  name: string | null;
  version: number;
  request: Partial<EditRequest>;
  rate: string;
  beats: Beat[];
  timeline: { duration: TimelineTime; title?: string | null; tracks: { events: TimelineEvent[] }[] };
  facts: EditFactsData;
  renders: RenderRow[];
}

export interface VersionItem {
  version: number;
  created_at: string;
}

export interface ReportEvent {
  event_id: string;
  beat_id: string | null;
  role: string;
  segment_id: string;
  source_file: string | null;
  timeline_in: TimelineTime;
  timeline_out: TimelineTime;
  reason: string | null;
  description: string | null;
}

export interface ReportNotUsed {
  selection_ref: string;
  segment_id: string;
  beat_id?: string | null;
  reason?: string | null;
  alternative_to?: string | null;
}

export interface ReportRejected {
  segment_id: string;
  asset_id: string;
  source: "user" | "ai";
  whole_clip: boolean;
  words: string[];
  source_file: string | null;
  camera: string | null;
}

/** `GET /edits/{eid}/report` (PRODUCT.md §7; ADR 0042, 0047). */
export interface ReportData {
  version: number;
  events: ReportEvent[];
  not_used: ReportNotUsed[];
  rejected: { total: number; offset: number; items: ReportRejected[] };
}

/** A timeline position as the player's exact time: ``frames`` ticks of ``1/rate``. */
export function toSource(t: TimelineTime): SourceTime {
  const [n, d] = parseRational(t.rate);
  return { ticks: t.frames, tb: `${d}/${n}` };
}

/** Display seconds of a timeline length (never stored). */
export function timelineSeconds(t: TimelineTime): number {
  const [n, d] = parseRational(t.rate);
  return (t.frames * d) / n;
}

export function timecode(t: TimelineTime): string {
  return formatClock(timelineSeconds(t));
}

/** Contiguous runs of one beat as coloured bar segments, the beat's order as its colour.
 * A shot outside every beat gets the colour after the last beat's. */
const TITLE_CARD = "\u0000title";

export function beatSegments(events: TimelineEvent[], beats: Beat[]): PlayerSegment[] {
  const order = new Map(beats.map((b, i) => [b.beat_id, i]));
  const out: (PlayerSegment & { beat: string | null })[] = [];
  for (const e of events) {
    const beat = e.kind === "title" ? TITLE_CARD : e.beat_id;
    const last = out.at(-1);
    if (last && last.beat === beat) {
      last.end = toSource(e.timeline_out);
      continue;
    }
    const i = order.get(e.beat_id ?? "") ?? beats.length;
    out.push({
      beat,
      start: toSource(e.timeline_in),
      end: toSource(e.timeline_out),
      label: beat === TITLE_CARD ? "Title" : (beats[i]?.title ?? "Other"),
      series: beat === TITLE_CARD ? 6 : (i % 6) + 1,
    });
  }
  return out.map(({ beat: _beat, ...seg }) => seg);
}

/** The beat playing at ``seconds`` (display), for the "Beat:" chip. */
export function beatAt(events: TimelineEvent[], beats: Beat[], seconds: number): string | null {
  const e = events.find((x) => timelineSeconds(x.timeline_in) <= seconds && seconds < timelineSeconds(x.timeline_out));
  return e ? (beats.find((b) => b.beat_id === e.beat_id)?.title ?? null) : null;
}

/** S17 EditFacts, as label/value pairs. */
export function factsRows(f: EditFactsData): [string, string][] {
  const dur = f.duration ? timelineSeconds(f.duration) : 0;
  const target = f.target.frames != null ? formatClock(timelineSeconds({ frames: f.target.frames, rate: f.target.rate })) : "—";
  const tol = f.tolerance.frames ? Math.round(timelineSeconds({ frames: f.tolerance.frames, rate: f.tolerance.rate })) : 0;
  return [
    ["Duration", f.duration ? formatClock(dur) : "—"],
    ["Target", tol ? `${target} ±${tol} s` : `${target} exactly`],
    ["Shots", String(f.shots)],
    ["Avg shot", f.shots ? `${(dur / f.shots).toFixed(1)} s` : "—"],
    ["Beats", String(f.beats)],
    ["Days", f.days_available ? `${f.days_used} of ${f.days_available}` : "—"],
    ["Photos", String(f.photos)],
    ["AI cost", f.ai_cost_usd == null ? "—" : f.ai_cost_usd === 0 ? "No AI cost" : `$${f.ai_cost_usd.toFixed(2)}`],
  ];
}

/** "IMG_4471.MOV" from a relative path. */
export function fileName(path: string | null): string | null {
  return path ? (path.split("/").at(-1) ?? path) : null;
}

const ROLE: Record<string, string> = {
  opener: "Opener",
  establishing: "Establishing",
  b_roll: "B-roll",
  hero: "Hero",
  detail: "Detail",
  action: "Action",
  people: "People",
  reaction: "Reaction",
  dialogue: "Dialogue",
  transition: "Transition",
  closer: "Closer",
};

export function roleLabel(role: string): string {
  return ROLE[role] ?? role.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** `GET /edits/{eid}/findings` items (ADR 0081, 0089). */
export interface Finding {
  finding_id: string;
  version: number;
  source: "critic" | "ai";
  code: string;
  severity: "blocking" | "warning" | "info";
  /** Timeline frame at the edit's rate. */
  frame: number;
  event_id: string | null;
  text: string;
  fix: string | null;
  can_apply: boolean;
  status: "open" | "applied" | "ignored";
  applied_in_version: number | null;
}

export const isIssue = (f: Finding) => f.severity !== "info";
