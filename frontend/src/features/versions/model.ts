import { fps } from "@/lib/time";

/** `GET /edits/{eid}/versions` items (ADR 0083, 0090). */
export interface VersionRow {
  version: number;
  created_at: string;
  duration: { frames: number; rate: string } | null;
  creator: "ai" | "user" | "system";
  reason: string | null;
  parent_version: number | null;
}

export type ChangeKind = "replaced" | "trimmed" | "moved" | "added" | "removed";

/** A `GET /edits/{eid}/compare` change, with S18's words (ADR 0090). */
export interface Change {
  kind: ChangeKind;
  ref: string;
  event_a: string | null;
  event_b: string | null;
  frame: number;
  in_version: number;
  moved: boolean;
  file_a: string | null;
  file_b: string | null;
  frames_a: number | null;
  frames_b: number | null;
  beat_a: string | null;
  beat_b: string | null;
}

export interface CompareData {
  a: number;
  b: number;
  duration_a: { frames: number; rate: string };
  duration_b: { frames: number; rate: string };
  same: boolean;
  changes: Change[];
}

export const KIND_LABEL: Record<ChangeKind, string> = { replaced: "Replaced", trimmed: "Trimmed", moved: "Moved", added: "Added", removed: "Removed" };

/** "+1.2 s" / "−0.8 s" (display). */
function delta(frames: number, rate: string): string {
  const s = Math.round((frames / fps(rate)) * 10) / 10;
  return `${s >= 0 ? "+" : "−"}${Math.abs(s).toFixed(1)} s`;
}

/** What a change says in S18's list: "IMG_4390.MOV → DSC_0932.MOV", "IMG_4472.MOV
 * extended +1.2 s", "Family photo → Finale", "GX030214.MP4". */
export function changeText(c: Change, rate: string): string {
  const name = c.file_b ?? c.file_a ?? c.ref;
  switch (c.kind) {
    case "replaced":
      return `${c.file_a ?? "a clip"} → ${c.file_b ?? "another clip"}`;
    case "trimmed": {
      const d = (c.frames_b ?? 0) - (c.frames_a ?? 0);
      return d === 0 ? `${name} trimmed` : `${name} ${d > 0 ? "extended" : "shortened"} ${delta(d, rate)}`;
    }
    case "moved":
      return c.beat_b && c.beat_b !== c.beat_a ? `${name} → ${c.beat_b}` : `${name} moved`;
    case "added":
      return `${name} added`;
    case "removed":
      return name;
  }
}

/** The two versions compared by default: the latest and the one before it. */
export function defaultPair(rows: VersionRow[]): [number, number] | null {
  if (rows.length < 2) return null;
  const sorted = rows.map((r) => r.version).sort((x, y) => x - y);
  return [sorted.at(-2)!, sorted.at(-1)!];
}
