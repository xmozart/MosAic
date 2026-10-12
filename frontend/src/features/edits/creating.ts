import type { Stage } from "@/components/system/StageList";
import { formatClock } from "@/lib/time";

/** `GET /jobs/{id}`'s state (API_MAP). */
export type JobState = "running" | "done" | "failed" | "cancelled" | "paused";

/** A generation's live view, in its job's result under `creating` (ADR 0087). */
export interface Creating {
  step?: "planning" | "selecting" | "fitting" | "checking";
  moments?: number;
  candidates?: number;
  beats?: { beat_id: string; title: string; intent: string; sample_ids?: number[] }[];
}

export interface CreatingJob {
  job_id: number;
  state: JobState;
  error: string | null;
  result: { creating?: Creating } | null;
}

/** Where S15 is: the generation, then the preview render. */
export interface CreatingStatus {
  generation: CreatingJob | undefined;
  /** The preview render's job, once the edit is made. */
  preview: { state: JobState } | undefined;
  /** The edit's target length in seconds (for "Fitting to 5:00"). */
  seconds: number;
}

const ORDER = ["candidates", "planning", "selecting", "fitting", "refining", "checking", "preview"] as const;
const AT: Record<NonNullable<Creating["step"]>, number> = { planning: 1, selecting: 2, fitting: 3, checking: 5 };

/** S15's step list (Finding candidates → … → Rendering preview) from the jobs' state. */
export function creatingStages(s: CreatingStatus): Stage[] {
  const c = s.generation?.result?.creating ?? {};
  const made = s.generation?.state === "done";
  const failed = s.generation?.state === "failed" || s.generation?.state === "cancelled";
  const paused = s.generation?.state === "paused";
  // The step running now: the generation's, then the preview once the edit is made.
  const now = made ? 6 : c.step ? AT[c.step] : 0;
  const previewDone = s.preview?.state === "done";
  const labels: Record<(typeof ORDER)[number], string> = {
    candidates: "Finding candidates",
    planning: "Planning the story",
    selecting: "Choosing shots",
    fitting: `Fitting to ${formatClock(s.seconds)}`,
    refining: "Refining cuts",
    checking: "Checking the edit",
    preview: "Rendering preview",
  };
  const notes: Partial<Record<(typeof ORDER)[number], string>> = {};
  if (c.candidates !== undefined) notes.candidates = `${c.moments ?? c.candidates} clips → ${c.candidates} candidates`;
  if (c.beats?.length) notes.planning = `${c.beats.length} beats`;
  const working = beatInProgress(c);
  if (working !== null && c.beats) notes.selecting = `Beat ${working + 1} of ${c.beats.length} · ${c.beats[working]!.title}`;
  return ORDER.map((key, i) => {
    // Fitting and refining are one step of the solver: they run and finish together.
    const at = key === "refining" ? 3 : i;
    let state: Stage["state"] = at < now ? "done" : at === now ? "running" : "pending";
    if (key === "preview" && previewDone) state = "done";
    if (key === "preview" && state === "running" && s.preview?.state === "failed") state = "failed";
    if (key === "preview" && state === "running" && s.preview?.state === "paused") state = "paused";
    if (failed && state === "running") state = "failed";
    if (paused && state === "running") state = "paused";
    return { key, label: labels[key], state, ...(notes[key] ? { note: notes[key] } : {}) };
  });
}

/** Which beat card is highlighted: the one being worked on while shots are chosen. */
export function beatInProgress(c: Creating | undefined): number | null {
  if (!c?.beats?.length || c.step !== "selecting") return null;
  const framed = c.beats.findIndex((b) => !b.sample_ids?.length);
  return framed === -1 ? null : framed;
}
