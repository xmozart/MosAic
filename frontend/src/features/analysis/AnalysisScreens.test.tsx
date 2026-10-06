import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { connectActivity } from "@/lib/activity";
import { useToasts } from "@/lib/toasts";

import { AnalysisProgressScreen } from "./AnalysisProgressScreen";
import { DeepenDialog } from "./DeepenDialog";
import { JOB, PROGRESS } from "./fixtures";

type Opts = { body?: unknown; params?: { path?: Record<string, unknown>; query?: Record<string, unknown> } };
const calls: { method: string; path: string; opts?: Opts }[] = [];
let replies: Record<string, unknown> = {};
const reply = (method: string, path: string, opts?: Opts) => {
  calls.push({ method, path, opts });
  const d = replies[`${method} ${path}`];
  if (d === undefined) return Promise.resolve({ error: { detail: "unmocked" }, response: { status: 404 } });
  return Promise.resolve({ data: typeof d === "function" ? (d as (o?: Opts) => unknown)(opts) : d, response: { status: 200 } });
};
vi.mock("@/api/client", () => ({
  api: {
    GET: (p: string, o?: Opts) => reply("GET", p, o),
    POST: (p: string, o?: Opts) => reply("POST", p, o),
  },
}));

function mount(path: string, element: React.ReactNode, route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={element} />
          <Route path="/p/:pid/analysis" element={<p>progress page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls.length = 0;
  replies = {};
  useToasts.setState({ items: [] });
});

describe("DeepenDialog", () => {
  beforeEach(() => {
    replies["GET /api/projects/{pid}/inventory"] = {
      days: [
        { date: "2026-07-15", n: 2, clips: 38 },
        { date: "2026-07-16", n: 3, clips: 44 },
      ],
    };
    replies["GET /api/projects/{pid}/trip-context"] = { days: [{ date: "2026-07-15", place: "Arenal" }] };
    replies["GET /api/projects/{pid}/analysis/estimate"] = {
      mode: "thorough",
      scope: "deepen",
      videos: 38,
      photos: 0,
      video_seconds: 600,
      segments: 40,
      l2_calls: 0,
      l3_calls: [3, 6],
      cost_usd: [0.4, 0.9],
      storage_bytes: 0,
      wall_seconds: [300, 420],
      basis: "default",
      days: 1,
    };
  });

  it("estimates the picked days by the server's numbers and starts them", async () => {
    replies["POST /api/projects/{pid}/analysis-runs"] = { job_id: 12 };
    mount("/p/P1/deepen", <DeepenDialog pid="P1" open onClose={() => {}} />, "/p/:pid/deepen");
    fireEvent.click(await screen.findByRole("checkbox", { name: /Day 2 · Arenal/ }));
    expect(await screen.findByText("About 6 min · $0.40–0.90")).toBeInTheDocument();
    const est = calls.filter((c) => c.path.endsWith("/estimate")).at(-1)!;
    expect(est.opts?.params?.query).toEqual({ mode: "thorough", scope: "days:2" });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByText("progress page")).toBeInTheDocument();
    const run = calls.find((c) => c.method === "POST")!;
    expect(run.opts?.body).toEqual({ mode: "thorough", scope: { kind: "days", days: [2], segment_ids: [] } });
  });

  it("nothing new to add starts nothing and says so", async () => {
    replies["POST /api/projects/{pid}/analysis-runs"] = { job_id: null };
    const close = vi.fn();
    mount("/p/P1/deepen", <DeepenDialog pid="P1" open onClose={close} />, "/p/:pid/deepen");
    fireEvent.click(await screen.findByRole("radio", { name: "Whole trip" }));
    await screen.findByText("About 6 min · $0.40–0.90"); // Start waits for the estimate
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(useToasts.getState().items.map((t) => t.message)).toEqual(["Nothing to add: that part of the trip already has this depth."]);
    expect(screen.queryByText("progress page")).toBeNull();
  });
});

describe("AnalysisProgressScreen", () => {
  it("resumes a cancelled deepening with its own scope, never a whole-project run", async () => {
    replies["GET /api/projects/{pid}/analysis/progress"] = {
      ...PROGRESS,
      kind: "deepen",
      mode: "thorough",
      deepen: { target: "thorough", days: [2, 3], segment_ids: [] },
    };
    replies["GET /api/jobs/{job_id}"] = { ...JOB, state: "cancelled" };
    replies["POST /api/projects/{pid}/analysis-runs"] = { job_id: 13 };
    mount("/p/P1/analysis?job=7", <AnalysisProgressScreen />, "/p/:pid/analysis");
    expect(await screen.findByText("Analysis cancelled")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume analysis" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.opts?.body).toEqual({
      mode: "thorough",
      scope: { kind: "days", days: [2, 3], segment_ids: [] },
      cost_limit: 10, // the limit the run had
    });
  });

  it("labels a running deepening and stops polling once the job is done", async () => {
    replies["GET /api/projects/{pid}/analysis/progress"] = { ...PROGRESS, kind: "deepen", mode: "thorough", deepen: { target: "thorough", days: [], segment_ids: [] } };
    replies["GET /api/jobs/{job_id}"] = JOB;
    const view = mount("/p/P1/analysis", <AnalysisProgressScreen />, "/p/:pid/analysis");
    expect(await screen.findByText("Deepening · Thorough")).toBeInTheDocument();
    view.unmount();
  });

  it("no analysis yet only on 404", async () => {
    mount("/p/P1/analysis", <AnalysisProgressScreen />, "/p/:pid/analysis");
    expect(await screen.findByText("No analysis yet")).toBeInTheDocument();
  });
});

describe("ready to browse", () => {
  it("toasts once per job, however often the stream repeats it", () => {
    const handlers: Record<string, (e: MessageEvent) => void> = {};
    class FakeSource {
      addEventListener(name: string, fn: (e: MessageEvent) => void) {
        handlers[name] = fn;
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeSource);
    const stop = connectActivity("/x");
    const ev = new MessageEvent("analysis.ready_to_browse", { data: JSON.stringify({ job_id: 99, project_id: "P1" }) });
    handlers["analysis.ready_to_browse"]!(ev);
    handlers["analysis.ready_to_browse"]!(ev); // a reconnect repeats it
    expect(useToasts.getState().items).toHaveLength(1);
    stop();
    vi.unstubAllGlobals();
  });
});
