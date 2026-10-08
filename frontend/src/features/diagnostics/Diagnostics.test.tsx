import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { useToasts } from "@/lib/toasts";

import { DiagnosticsScreen } from "./DiagnosticsScreen";
import { DiagnosticsView, type DiagnosticsViewProps } from "./DiagnosticsView";
import { DONE_AI, FAILED, ROWS } from "./fixtures";
import { LIVE, cost, duration, tokens, type TaskDetail, type TaskRow } from "./model";

const noop = () => {};
const base: DiagnosticsViewProps = {
  filter: "all",
  onFilter: noop,
  projects: [{ id: "P1", name: "Costa Rica 2026" }],
  project: null,
  onProject: noop,
  rows: ROWS,
  selected: 3,
  onSelect: noop,
  detail: FAILED,
  onRetryTask: noop,
  onSkipTask: noop,
  onExport: noop,
};

it("formats time, tokens and cost as the mockup does", () => {
  expect([null, 400, 4200, 38100, 125000].map(duration)).toEqual(["—", "0.4 s", "4.2 s", "38.1 s", "2 m 05 s"]);
  expect([59960, 119500].map(duration)).toEqual(["1 m 00 s", "2 m 00 s"]); // never "60.0 s" or "1 m 60 s"
  expect(tokens({ tokens_in: 1840, tokens_out: 610 })).toBe("1,840 / 610 tok");
  expect(tokens({ tokens_in: null, tokens_out: null })).toBe("—");
  expect([null, 0, 0.004, 0.38].map(cost)).toEqual(["—", "$0", "$0.004", "$0.38"]);
});

describe("DiagnosticsView", () => {
  it("the table shows each task's tool, time, tokens and cost", () => {
    render(<DiagnosticsView {...base} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(6);
    const vision = within(rows[0]!);
    expect(vision.getByText("anthropic · claude-haiku-4-5")).toBeInTheDocument();
    expect(vision.getByText("1,840 / 610 tok")).toBeInTheDocument();
    expect(vision.getByText("$0.004")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("failed")).toHaveClass("text-reject");
    expect(within(rows[4]!).getByText("running")).toBeInTheDocument();
    expect(within(rows[3]!).getByRole("button", { name: "media.probe" })).toHaveAttribute("aria-current", "true");
  });

  it("a failure's detail: error output, attempts, worker, Retry and Skip", () => {
    const retry = vi.fn();
    const skip = vi.fn();
    render(<DiagnosticsView {...base} onRetryTask={retry} onSkipTask={skip} />);
    const d = within(screen.getByRole("region", { name: "Task detail" }));
    expect(d.getByText(/moov atom not found/)).toBeInTheDocument();
    expect(d.getByText("2 of 3")).toBeInTheDocument();
    expect(d.getByText("io-2")).toBeInTheDocument();
    fireEvent.click(d.getByRole("button", { name: /Retry/ }));
    fireEvent.click(d.getByRole("button", { name: /Skip/ }));
    expect(retry).toHaveBeenCalledWith(3);
    expect(skip).toHaveBeenCalledWith(3);
  });

  it("a success's detail has no actions; filters and the trip pick call back", () => {
    const filter = vi.fn();
    const proj = vi.fn();
    const select = vi.fn();
    render(<DiagnosticsView {...base} selected={6} detail={DONE_AI} onFilter={filter} onProject={proj} onSelect={select} />);
    const d = within(screen.getByRole("region", { name: "Task detail" }));
    expect(d.getByRole("button", { name: /Retry/ })).toBeDisabled();
    expect(d.getByText("Retry and Skip are for failed tasks.")).toBeInTheDocument();
    expect(d.queryByText("Error output")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Failed" }));
    expect(filter).toHaveBeenCalledWith("failed");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "P1" } });
    expect(proj).toHaveBeenCalledWith("P1");
    fireEvent.click(screen.getByRole("button", { name: "media.proxy" }));
    expect(select).toHaveBeenCalledWith(5);
  });

  it("empty, loading and nothing-selected states", () => {
    const { rerender } = render(<DiagnosticsView {...base} rows={[]} selected={null} detail={undefined} />);
    expect(screen.getByText("No tasks yet.")).toBeInTheDocument();
    expect(screen.getByText("Pick a task to see what it did.")).toBeInTheDocument();
    rerender(<DiagnosticsView {...base} rows={undefined} filter="failed" selected={null} detail={undefined} />);
    expect(screen.getByLabelText("Loading tasks")).toBeInTheDocument();
    rerender(<DiagnosticsView {...base} rows={[]} filter="failed" selected={null} detail={undefined} />);
    expect(screen.getByText("No tasks are failed.")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ screen

const calls: { method: string; path: string; params?: unknown }[] = [];
const server = {
  rows: [] as TaskRow[],
  next: null as number | null,
  detail: FAILED as TaskDetail,
  actionError: null as string | null,
  bundleFails: false,
};
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string, o?: { params?: { query?: Record<string, unknown> } }) => {
      calls.push({ method: "GET", path, params: o?.params });
      if (path === "/api/projects") return Promise.resolve({ data: { items: [{ id: "P1", name: "Costa Rica 2026" }] } });
      if (path === "/api/diagnostics/tasks") {
        const cursor = o?.params?.query?.cursor;
        return Promise.resolve({ data: cursor ? { items: [{ ...server.rows[0]!, task_id: 99, input: "older.MOV" }], next_cursor: null } : { items: server.rows, next_cursor: server.next } });
      }
      if (path === "/api/diagnostics/tasks/{tid}") return Promise.resolve({ data: server.detail });
      return Promise.resolve({ error: { detail: "x" } });
    },
    POST: (path: string, o?: { params?: unknown }) => {
      calls.push({ method: "POST", path, params: o?.params });
      if (path === "/api/diagnostics/bundle") return Promise.resolve(server.bundleFails ? { error: {} } : { data: new Blob(["zip"]) });
      return Promise.resolve(server.actionError ? { error: { detail: server.actionError } } : { data: { task_id: 3 } });
    },
  },
}));

function Where() {
  const l = useLocation();
  return <span data-testid="where">{l.search}</span>;
}

function mount(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/diagnostics"
            element={
              <>
                <DiagnosticsScreen />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const listCalls = () => calls.filter((c) => c.path === "/api/diagnostics/tasks").length;

beforeEach(() => {
  calls.length = 0;
  server.rows = ROWS.filter((r) => !LIVE.has(r.status));
  server.next = null;
  server.detail = FAILED;
  server.actionError = null;
  server.bundleFails = false;
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.useRealTimers());

it("DiagnosticsScreen filters in the URL, opens a task, retries it and exports the bundle", async () => {
  mount("/diagnostics?status=failed");
  expect(await screen.findByRole("button", { name: "media.probe" })).toBeInTheDocument();
  expect(calls.find((c) => c.path === "/api/diagnostics/tasks")?.params).toEqual({ query: { limit: 100, status: "failed" } });
  expect(screen.getByRole("radio", { name: "Failed" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(screen.getByRole("button", { name: "media.probe" }));
  const d = within(await screen.findByRole("region", { name: "Task detail" }));
  fireEvent.click(d.getByRole("button", { name: /Retry/ }));
  await waitFor(() => expect(calls).toContainEqual({ method: "POST", path: "/api/diagnostics/tasks/{tid}/retry", params: { path: { tid: 3 } } }));
  fireEvent.click(screen.getByRole("button", { name: /Export diagnostic bundle/ }));
  await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  expect(calls.some((c) => c.path === "/api/diagnostics/bundle")).toBe(true);
});

it("the list polls while a task is waiting or running, and stops when none is", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  server.rows = ROWS; // includes running and waiting tasks
  mount("/diagnostics");
  await screen.findByRole("button", { name: "media.visual" });
  const before = listCalls();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3100);
  });
  expect(listCalls()).toBeGreaterThan(before);
  server.rows = ROWS.filter((r) => !LIVE.has(r.status)); // everything finished
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3100);
  });
  const settled = listCalls();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9000);
  });
  expect(listCalls()).toBe(settled);
});

it("a running task's detail polls until it ends", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  server.detail = { ...FAILED, status: "leased", can_retry: false, can_skip: false, error: null };
  mount("/diagnostics");
  fireEvent.click(await screen.findByRole("button", { name: "media.probe" }));
  await screen.findByRole("region", { name: "Task detail" });
  const detailCalls = () => calls.filter((c) => c.path === "/api/diagnostics/tasks/{tid}").length;
  const first = detailCalls();
  server.detail = FAILED;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3100);
  });
  expect(detailCalls()).toBeGreaterThan(first);
  expect(await screen.findByText(/moov atom not found/)).toBeInTheDocument();
  const done = detailCalls();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9000);
  });
  expect(detailCalls()).toBe(done);
});

it("Show more pages by cursor; a new filter or trip clears the selection", async () => {
  server.next = 3;
  mount("/diagnostics");
  fireEvent.click(await screen.findByRole("button", { name: "Show more" }));
  expect(await screen.findByText("older.MOV")).toBeInTheDocument();
  expect(calls.some((c) => (c.params as { query?: { cursor?: number } })?.query?.cursor === 3)).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "media.probe" }));
  await screen.findByRole("region", { name: "Task detail" });
  fireEvent.click(screen.getByRole("radio", { name: "Failed" }));
  expect(screen.getByTestId("where")).toHaveTextContent("?status=failed");
  expect(await screen.findByText("Pick a task to see what it did.")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "P1" } });
  expect(screen.getByTestId("where")).toHaveTextContent("project=P1");
});

it("a refused retry shows the server's reason; a failed bundle says so; a bad ?status= is All", async () => {
  server.actionError = "This task's project was removed from MosAic.";
  mount("/diagnostics?status=bogus");
  expect(await screen.findByRole("button", { name: "media.probe" })).toBeInTheDocument();
  expect(calls.find((c) => c.path === "/api/diagnostics/tasks")?.params).toEqual({ query: { limit: 100 } });
  expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(screen.getByRole("button", { name: "media.probe" }));
  fireEvent.click(within(await screen.findByRole("region", { name: "Task detail" })).getByRole("button", { name: /Retry/ }));
  await waitFor(() => expect(useToasts.getState().items.at(-1)?.message).toBe("This task's project was removed from MosAic."));
  server.bundleFails = true;
  fireEvent.click(screen.getByRole("button", { name: /Export diagnostic bundle/ }));
  await waitFor(() => expect(useToasts.getState().items.at(-1)?.message).toBe("Couldn't prepare the bundle. Try again."));
});
