import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { ActivityPopover } from "@/components/shell/ActivityPopover";
import { connectActivity, useActivity } from "@/lib/activity";

import { AppShell, Placeholder } from "./AppShell";
import { ProjectLayout } from "./ProjectLayout";

const ROW = {
  id: "p1",
  name: "Costa Rica 2026",
  placement: "in_folder",
  fs_class: "local",
  status: { state: "analyzed", mode: "balanced" },
};

function mount(path: string, seed?: (qc: QueryClient) => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(["projects"], { items: [ROW] });
  seed?.(qc);
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Placeholder title="Your trips" />} />
            <Route path="p/:pid" element={<ProjectLayout />}>
              <Route path="*" element={<Placeholder title="Library" />} />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  beforeEach(() => useActivity.setState({ jobs: {}, lost: [], readOnly: [] }));

  it("renders without looping and shows live activity", () => {
    mount("/");
    expect(screen.getByText("Your trips")).toBeInTheDocument();
    act(() =>
      useActivity.getState().upsert({
        jobId: 1, projectId: "p1", kind: "analysis", state: "running", pct: 42, stage: null, item: null, cost: 0,
      }),
    );
    expect(screen.getByLabelText("Background activity: 42%")).toBeInTheDocument();
  });

  it("names app-level jobs MosAic (model downloads; ADR 0058)", () => {
    mount("/");
    act(() =>
      useActivity.getState().upsert({
        jobId: 9, projectId: "_app", kind: "models", state: "running", pct: 30, stage: "downloading", item: null, cost: 0,
      }),
    );
    fireEvent.click(screen.getByLabelText("Background activity: 30%"));
    expect(screen.getByText("Downloading models · MosAic")).toBeInTheDocument();
  });

  it("stays read-only after the lost-lease dialog is acknowledged", () => {
    mount("/p/p1/library");
    expect(screen.getByText("Costa Rica 2026")).toBeInTheDocument();
    act(() => useActivity.getState().markLost("p1"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Continue read-only"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText(/You can look, but changes are off/)).toBeInTheDocument();
    expect(screen.getByText("Costa Rica 2026").closest("button")).toBeDisabled();
  });

  it("waits while the trip's data moves, then shows the screen (ADR 0055)", () => {
    mount("/p/p1/library");
    act(() =>
      useActivity.getState().upsert({
        jobId: 7, projectId: "p1", kind: "move", state: "running", pct: 30, stage: "moving", item: null, cost: 0,
      }),
    );
    expect(screen.getByText(/Moving this trip's data/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Library" })).toBeNull();
    act(() => useActivity.getState().setState(7, "done"));
    expect(screen.queryByText(/Moving this trip's data/)).toBeNull();
    expect(screen.getByRole("heading", { name: "Library" })).toBeInTheDocument();
  });

  it("finds a move already running when the trip opens", () => {
    mount("/p/p1/library", (qc) => qc.setQueryData(["moving", "p1"], [{ job_id: 3, kind: "move" }]));
    expect(screen.getByText(/Moving this trip's data/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Library" })).toBeNull();
  });

  it("says when a trip is unknown", () => {
    mount("/p/nope/library");
    expect(screen.getByText(/We can't find that trip/)).toBeInTheDocument();
  });
});

describe("activity stream", () => {
  it("forgets jobs on reconnect: ended jobs never linger in the ring", () => {
    const sources: FakeSource[] = [];
    class FakeSource {
      listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
      constructor() {
        sources.push(this);
      }
      addEventListener(type: string, fn: (e: MessageEvent) => void) {
        (this.listeners[type] ??= []).push(fn);
      }
      emit(type: string, data?: unknown) {
        for (const fn of this.listeners[type] ?? []) fn(new MessageEvent(type, { data: JSON.stringify(data ?? {}) }));
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeSource);
    useActivity.setState({ jobs: {}, lost: [], readOnly: [] });
    const stop = connectActivity();
    const es = sources[0]!;
    es.emit("open");
    es.emit("job.progress", { job_id: 7, project_id: "p", kind: "analysis", state: "running", pct: 50, stage: null, item: null, cost: 0 });
    expect(Object.keys(useActivity.getState().jobs)).toEqual(["7"]);
    es.emit("open"); // reconnected; the job finished meanwhile, so it is not resent
    expect(useActivity.getState().jobs).toEqual({});
    es.emit("lock.lost", { project_id: "p" });
    expect(useActivity.getState().lost).toEqual(["p"]);
    stop();
    vi.unstubAllGlobals();
  });
});

describe("ActivityPopover actions", () => {
  it.each([
    ["running", ["Pause", "Cancel"]],
    ["pending", ["Pause", "Cancel"]],
    ["paused", ["Resume", "Cancel"]],
    ["paused_cost_limit", ["Raise limit…", "Cancel"]],
  ])("%s → %j", (state, labels) => {
    render(
      <ActivityPopover
        defaultOpen
        jobs={[{ jobId: 1, projectId: "p", kind: "media.cloud_download", state, pct: 5, stage: null, item: null, cost: 0 }]}
        projectNames={{ p: "Trip" }}
        onPause={() => {}}
        onResume={() => {}}
        onCancel={() => {}}
        onRaiseLimit={() => {}}
      >
        <button type="button">ring</button>
      </ActivityPopover>,
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent).filter((t) => t !== "ring");
    expect(buttons).toEqual(labels);
    expect(screen.getByText(/Working · Trip/)).toBeInTheDocument(); // never the internal kind
  });
});
