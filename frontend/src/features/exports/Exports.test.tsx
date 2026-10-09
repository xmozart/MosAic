import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { renderRow } from "@/features/preview/fixtures";
import { renderTime } from "@/lib/renders";

import { ExportsIndex, ExportsScreen } from "./ExportsScreen";
import { ExportsView, type ExportsViewProps } from "./ExportsView";
import { ROWS } from "./fixtures";

const noop = () => {};
const base: ExportsViewProps = {
  folder: "Costa_Rica_2026/MosAic/renders",
  items: ROWS,
  coverUrl: (i) => `/f/${i}`,
  fileUrl: (r, download) => `/file/${r.render_id}${download ? "?dl" : ""}`,
  onCancel: noop,
  onRerender: noop,
  onDeleteFile: noop,
  onEdits: noop,
};

const rows = () => screen.getAllByRole("row").slice(1);

it("render times read as the mockup does", () => {
  expect([null, 40, 552, 280, 3900].map(renderTime)).toEqual(["—", "40 s", "9 m 12 s", "4 m 40 s", "1 h 05 m"]);
});

describe("ExportsView", () => {
  it("every row says its edit, preset, status, size and time", () => {
    render(<ExportsView {...base} />);
    expect(screen.getByText("Costa_Rica_2026/MosAic/renders")).toBeInTheDocument();
    const [rendering, queued, done, failed] = rows().map((r) => within(r));
    expect(rendering!.getByText("Rendering 58%")).toBeInTheDocument();
    expect(rendering!.getByText("Web · 4K")).toBeInTheDocument();
    expect(queued!.getByText("Queued")).toBeInTheDocument();
    expect(queued!.getByText("Web · 1080p vertical")).toBeInTheDocument();
    expect(done!.getByText("18 GB")).toBeInTheDocument();
    expect(done!.getByText("9 m 12 s")).toBeInTheDocument();
    expect(done!.getByRole("link", { name: /^Open Costa Rica/ })).toHaveAttribute("href", "/file/3");
    expect(done!.getByRole("link", { name: /^Download Costa Rica/ })).toHaveAttribute("href", "/file/3?dl");
    expect(failed!.getByText("Stopped at 30%")).toBeInTheDocument();
  });

  it("actions: cancel, remove, details then re-render, and delete with a confirmation", () => {
    const cancel = vi.fn();
    const again = vi.fn();
    const del = vi.fn();
    render(<ExportsView {...base} onCancel={cancel} onRerender={again} onDeleteFile={del} />);
    const [rendering, queued, done, failed] = rows().map((r) => within(r));
    fireEvent.click(rendering!.getByRole("button", { name: /^Cancel / }));
    fireEvent.click(queued!.getByRole("button", { name: /Remove/ }));
    expect(cancel.mock.calls.map((c) => c[0].render_id)).toEqual([5, 4]);
    fireEvent.click(failed!.getByRole("button", { name: /^Details/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("h264_videotoolbox failed (-12902)");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Re-render" }));
    expect(again.mock.calls[0]![0].render_id).toBe(2);
    fireEvent.click(done!.getByRole("button", { name: /Delete the file/ }));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete file" }));
    expect(del.mock.calls[0]![0].render_id).toBe(3);
  });

  it("re-render after cancel, delete or a missing file; busy rows wait", () => {
    const again = vi.fn();
    render(
      <ExportsView
        {...base}
        onRerender={again}
        busy={new Set([8])}
        items={[renderRow(9, { status: "cancelled" }), renderRow(8, { status: "deleted" }), renderRow(7, { status: "missing" })]}
      />,
    );
    const [cancelled, deleted, missing] = rows().map((r) => within(r));
    expect(deleted!.getByText("File deleted")).toBeInTheDocument();
    expect(missing!.getByText("File missing")).toBeInTheDocument();
    expect(deleted!.getByRole("button", { name: /^Re-render/ })).toBeDisabled();
    fireEvent.click(cancelled!.getByRole("button", { name: /^Re-render/ }));
    expect(again).toHaveBeenCalledTimes(1);
  });

  it("a busy row's Re-render waits in the Details dialog too", () => {
    render(<ExportsView {...base} busy={new Set([2])} />);
    fireEvent.click(rows()[3]!.querySelector("button")!);
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Re-render" })).toBeDisabled();
  });

  it("empty, loading, failed and more pages", () => {
    const edits = vi.fn();
    const more = vi.fn();
    const retry = vi.fn();
    const { rerender } = render(<ExportsView {...base} items={[]} onEdits={edits} />);
    fireEvent.click(screen.getByRole("button", { name: "Go to Edits" }));
    expect(edits).toHaveBeenCalled();
    rerender(<ExportsView {...base} items={undefined} />);
    expect(screen.getByLabelText("Loading exports")).toBeInTheDocument();
    rerender(<ExportsView {...base} items={undefined} error onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    rerender(<ExportsView {...base} hasMore onMore={more} />);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(more).toHaveBeenCalled();
  });
});

// ------------------------------------------------------------------ screen

const calls: { method: string; path: string; params?: unknown }[] = [];
let projectsList: { id: string }[] | null = [{ id: "P1" }];
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string, o?: { params?: { query?: Record<string, unknown> } }) => {
      calls.push({ method: "GET", path, params: o?.params });
      if (path === "/api/projects") return Promise.resolve(projectsList ? { data: { items: projectsList } } : { error: { detail: "down" } });
      const cursor = o?.params?.query?.cursor;
      if (cursor === undefined) return Promise.resolve({ data: { items: ROWS.slice(0, 3), next_cursor: 3, folder: "/trip/MosAic/renders" } });
      return Promise.resolve({ data: { items: ROWS.slice(3), next_cursor: null, folder: "/trip/MosAic/renders" } });
    },
    POST: (path: string, o: { params: unknown }) => {
      calls.push({ method: "POST", path, params: o.params });
      return Promise.resolve({ data: {} });
    },
    DELETE: (path: string, o: { params: unknown }) => {
      calls.push({ method: "DELETE", path, params: o.params });
      return Promise.resolve({ data: {} });
    },
  },
}));

function mount(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/exports" element={<ExportsIndex />} />
          <Route path="/p/:pid/exports" element={<ExportsScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("ExportsScreen pages the queue and runs the row actions", async () => {
  calls.length = 0;
  mount("/p/P1/exports");
  expect(await screen.findByText("Rendering 58%")).toBeInTheDocument();
  expect(screen.getByText("/trip/MosAic/renders")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show more" }));
  expect(await screen.findByText("Stopped at 30%")).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/projects/{pid}/renders" && JSON.stringify(c.params).includes('"cursor":3'))).toBe(true);
  fireEvent.click(screen.getAllByRole("button", { name: /^Cancel / })[0]!);
  await waitFor(() =>
    expect(calls).toContainEqual({ method: "POST", path: "/api/projects/{pid}/renders/{rid}/{action}", params: { path: { pid: "P1", rid: 5, action: "cancel" } } }),
  );
  fireEvent.click(screen.getAllByRole("button", { name: /Delete the file/ })[0]!);
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete file" }));
  await waitFor(() => expect(calls).toContainEqual({ method: "DELETE", path: "/api/projects/{pid}/renders/{rid}/file", params: { path: { pid: "P1", rid: 3 } } }));
});

it("/exports opens the newest trip's exports, or says to open a trip", async () => {
  projectsList = [{ id: "P1" }];
  mount("/exports");
  expect(await screen.findByText("Rendering 58%")).toBeInTheDocument();
  projectsList = [];
  mount("/exports");
  expect(await screen.findByText("Open a trip to see its exports.")).toBeInTheDocument();
});

it("/exports says when the trips couldn't be loaded, and tries again", async () => {
  projectsList = null;
  calls.length = 0;
  mount("/exports");
  expect(await screen.findByText("We couldn't load your trips.")).toBeInTheDocument();
  projectsList = [{ id: "P1" }];
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Rendering 58%")).toBeInTheDocument();
});

it("while a render runs, only the first page polls", async () => {
  calls.length = 0;
  mount("/p/P1/exports");
  expect(await screen.findByText("Rendering 58%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show more" }));
  expect(await screen.findByText("Stopped at 30%")).toBeInTheDocument();
  const pageCalls = () => calls.filter((c) => c.path === "/api/projects/{pid}/renders");
  const before = pageCalls().length;
  // One real poll interval: the poll timer starts before any fake clock could take over.
  await new Promise((r) => setTimeout(r, 2600));
  const polled = pageCalls().slice(before);
  expect(polled.length).toBeGreaterThan(0);
  expect(polled.every((c) => !JSON.stringify(c.params).includes("cursor"))).toBe(true);
  expect(screen.getByText("Stopped at 30%")).toBeInTheDocument(); // later pages stay shown
});
