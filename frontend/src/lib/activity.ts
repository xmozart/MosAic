import { create } from "zustand";

import { useToasts } from "@/lib/toasts";

/** One running job as the rail and its popover show it (S0). */
export interface JobSummary {
  jobId: number;
  projectId: string;
  kind: string;
  state: string; // running | paused | paused_cost_limit | done | failed | cancelled
  pct: number;
  stage: string | null;
  item: string | null;
  cost: number;
}

const DONE = new Set(["done", "failed", "cancelled"]);

interface ActivityState {
  jobs: Record<number, JobSummary>;
  lost: string[]; // projects another computer took over (lock.lost), not yet acknowledged
  readOnly: string[]; // projects the user keeps looking at read-only after losing them
  upsert: (j: JobSummary) => void;
  setState: (jobId: number, state: string) => void;
  markLost: (projectId: string) => void;
  /** The user saw the dialog: the project stays read-only (S0), only the dialog goes. */
  ackLost: (projectId: string) => void;
  reset: () => void;
}

export const useActivity = create<ActivityState>((set) => ({
  jobs: {},
  lost: [],
  readOnly: [],
  upsert: (j) => set((s) => ({ jobs: { ...s.jobs, [j.jobId]: { ...s.jobs[j.jobId], ...j } } })),
  setState: (jobId, state) =>
    set((s) => {
      const j = s.jobs[jobId];
      if (!j) return s;
      if (DONE.has(state)) {
        const rest = { ...s.jobs };
        delete rest[jobId];
        return { jobs: rest };
      }
      return { jobs: { ...s.jobs, [jobId]: { ...j, state } } };
    }),
  markLost: (projectId) => set((s) => (s.lost.includes(projectId) ? s : { lost: [...s.lost, projectId] })),
  ackLost: (projectId) =>
    set((s) => ({
      lost: s.lost.filter((p) => p !== projectId),
      readOnly: s.readOnly.includes(projectId) ? s.readOnly : [...s.readOnly, projectId],
    })),
  reset: () => set({ jobs: {} }),
}));

/** Jobs that are running now (the ring pulses only then). */
export function anyRunning(jobs: JobSummary[]): boolean {
  return jobs.some((j) => j.state === "running");
}

/** Overall progress of the running jobs, for the rail ring: the mean of their percents. */
export function overall(jobs: JobSummary[]): number | null {
  const running = jobs.filter((j) => !DONE.has(j.state));
  if (!running.length) return null;
  return Math.round(running.reduce((s, j) => s + j.pct, 0) / running.length);
}

/** Analysis jobs already announced as ready to browse (deduplicated across reconnects). */
const announced = new Set<number>();

/** Feeds the store from the server's event stream (all projects). */
export function connectActivity(url = "/api/events"): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const es = new EventSource(url, { withCredentials: true });
  const store = useActivity.getState;
  // Each (re)connection resends every active job; jobs that ended while disconnected
  // would otherwise never get their final event.
  es.addEventListener("open", () => store().reset());
  es.addEventListener("job.progress", (e) => {
    const d = JSON.parse((e as MessageEvent).data) as {
      job_id: number;
      project_id: string;
      kind: string;
      state: string;
      pct: number;
      stage: string | null;
      item: string | null;
      cost: number;
    };
    if (DONE.has(d.state)) {
      store().setState(d.job_id, d.state);
      return;
    }
    store().upsert({
      jobId: d.job_id,
      projectId: d.project_id,
      kind: d.kind,
      state: d.state,
      pct: d.pct,
      stage: d.stage,
      item: d.item,
      cost: d.cost,
    });
  });
  es.addEventListener("job.state", (e) => {
    const d = JSON.parse((e as MessageEvent).data) as { job_id: number; state: string };
    store().setState(d.job_id, d.state);
  });
  es.addEventListener("analysis.ready_to_browse", (e) => {
    const d = JSON.parse((e as MessageEvent).data) as { job_id: number; project_id: string };
    if (announced.has(d.job_id)) return; // a reconnect may repeat it (API_MAP)
    announced.add(d.job_id);
    useToasts.getState().push({
      kind: "success",
      message: "Your footage is ready to browse and edit. Deeper analysis continues in the background.",
    });
  });
  es.addEventListener("lock.lost", (e) => {
    const d = JSON.parse((e as MessageEvent).data) as { project_id: string };
    store().markLost(d.project_id);
  });
  return () => es.close();
}
