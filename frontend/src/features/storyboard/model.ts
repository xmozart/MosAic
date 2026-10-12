import { fps, type SourceTime } from "@/lib/time";

/** `GET /edits/{eid}/draft`'s board (ADR 0067). */
export interface BoardShot {
  ref: string;
  segment_id: string;
  role: string;
  length: string;
  reason: string;
  locked: boolean;
  /** Part of another shot's locked cut: it moves and locks with that one. */
  absorbed_by: string | null;
}

export interface BoardBeat {
  beat_id: string;
  title: string;
  intent: string;
  share_percent: number;
  shots: BoardShot[];
}

/** What S16 shows of a clip (ADR 0088). */
export interface ShotMedia {
  sample_id: number | null;
  file: string | null;
  day: number | null;
  photo: boolean;
  asset: number;
  range: { start: SourceTime; end: SourceTime };
}

export interface TimelineEvent {
  event_id: string;
  kind: string;
  beat_id: string | null;
  duration: { frames: number; rate: string };
  origin?: { selection_ref: string; merged?: string[] };
}

export interface DraftState {
  base_version: number;
  dirty: boolean;
  /** Ops in the draft (a new op or an undo changes it). */
  ops: number;
  can_undo: boolean;
  can_redo: boolean;
  board: { title: string; beats: BoardBeat[] };
  duration: { frames: number; rate: string };
  target: { frames: number | null; rate: string };
  tolerance: { frames: number; rate: string };
  timeline: { tracks: { events: TimelineEvent[] }[] };
  metrics: { locks?: { over_frames: number; frames: number; shots: number } };
  media: Record<string, ShotMedia>;
  /** Beats with a regenerate job running (ADR 0069), and the story or edit as a whole. */
  regenerating: string[];
  regenerating_scope: "story" | "all" | null;
}

export interface Alternative {
  segment_id: string;
  sample_id: number | null;
  file: string | null;
  day: number | null;
  photo: boolean;
  why_not: string | null;
  line: string;
}

/** A draft op (`POST /draft/ops`), as S16 sends them. */
export type DraftOp =
  | { kind: "move_shot"; ref: string; beat_id: string; index: number }
  | { kind: "move_beat"; beat_id: string; index: number }
  | { kind: "remove_shot"; ref: string }
  | { kind: "lock_shot"; ref: string; locked: boolean }
  | { kind: "replace_shot"; ref: string; segment_id: string }
  | { kind: "pace_beat"; beat_id: string; faster: boolean };

/** Display seconds of frames at a rate. */
export function frameSeconds(frames: number, rate: string): number {
  return frames / fps(rate);
}

/** Each shot's length on the timeline now, by storyboard ref (a shot cut together with a
 * locked one counts in that one's event). Shots not in the edit are missing. */
export function shotFrames(d: DraftState): Map<string, number> {
  const out = new Map<string, number>();
  for (const e of d.timeline.tracks[0]?.events ?? []) {
    if (e.origin?.selection_ref) out.set(e.origin.selection_ref, e.duration.frames);
  }
  return out;
}

/** Each beat's length on the timeline now (its shot events). */
export function beatFrames(d: DraftState): Map<string, number> {
  const out = new Map<string, number>();
  for (const e of d.timeline.tracks[0]?.events ?? []) {
    if (e.beat_id && e.kind !== "title") out.set(e.beat_id, (out.get(e.beat_id) ?? 0) + e.duration.frames);
  }
  return out;
}

/** A beat is locked when every shot in it is (S16 "Locked" pill and `user` border). */
export function beatLocked(b: BoardBeat): boolean {
  return b.shots.length > 0 && b.shots.every((s) => s.locked || s.absorbed_by !== null);
}

export function shotCount(d: DraftState): number {
  return d.board.beats.reduce((n, b) => n + b.shots.filter((s) => !s.absorbed_by).length, 0);
}

/** Where a dragged shot lands: the op that moves it to ``index`` in ``beat``, or null
 * when that is where it already is. The index is in the target beat as it is now; moving
 * down within one beat accounts for the shot leaving its old place. */
export function moveShotOp(board: BoardBeat[], ref: string, beatId: string, index: number): DraftOp | null {
  const from = board.find((b) => b.shots.some((s) => s.ref === ref));
  if (!from) return null;
  const at = from.shots.findIndex((s) => s.ref === ref);
  let to = index;
  if (from.beat_id === beatId) {
    if (to > at) to -= 1;
    if (to === at) return null;
  }
  return { kind: "move_shot", ref, beat_id: beatId, index: Math.max(0, to) };
}

export function moveBeatOp(board: BoardBeat[], beatId: string, index: number): DraftOp | null {
  const at = board.findIndex((b) => b.beat_id === beatId);
  if (at === -1) return null;
  let to = index;
  if (to > at) to -= 1;
  return to === at ? null : { kind: "move_beat", beat_id: beatId, index: to };
}
