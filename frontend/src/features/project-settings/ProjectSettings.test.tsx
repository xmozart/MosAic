import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router";

import { useToasts } from "@/lib/toasts";

import { CONTEXT, DEVICES, SETTINGS, STORAGE } from "./fixtures";
import { ProjectSettingsScreen } from "./ProjectSettingsScreen";
import { ProjectSettingsView, type ProjectSettingsViewProps } from "./ProjectSettingsView";

const noop = () => {};
const base: ProjectSettingsViewProps = {
  name: "Costa Rica 2026",
  folder: "/Volumes/Travel/Costa_Rica_2026",
  placement: "in_folder",
  onRename: noop,
  settings: SETTINGS,
  onSetting: noop,
  onAnalysisSetup: noop,
  devices: DEVICES,
  onCheckClocks: noop,
  context: CONTEXT,
  onEditContext: noop,
  storage: STORAGE,
  onClear: noop,
  onRemove: noop,
};

describe("ProjectSettingsView", () => {
  it("rows show their effective value and source; Reset and edits call back", () => {
    const set = vi.fn();
    render(<ProjectSettingsView {...base} onSetting={set} />);
    const analysis = within(screen.getByRole("region", { name: "Analysis" }));
    expect(analysis.getByText("From: this project")).toBeInTheDocument();
    expect(analysis.getByText("From: your preference")).toBeInTheDocument();
    expect(analysis.getByText("From: default")).toBeInTheDocument();
    fireEvent.click(analysis.getAllByRole("button", { name: "Reset" })[0]!);
    expect(set).toHaveBeenLastCalledWith("analysis.mode", null);
    fireEvent.click(analysis.getByRole("radio", { name: "Thorough" }));
    expect(set).toHaveBeenLastCalledWith("analysis.mode", "thorough");
    const limit = analysis.getByLabelText("AI cost limit in dollars");
    fireEvent.change(limit, { target: { value: "25" } });
    fireEvent.blur(limit);
    expect(set).toHaveBeenLastCalledWith("analysis.cost_limit_usd", 25);
    fireEvent.change(limit, { target: { value: "-3" } });
    fireEvent.blur(limit);
    expect(set).toHaveBeenCalledTimes(3); // a negative limit is never sent
    fireEvent.click(analysis.getByRole("switch", { name: "Use GPS for analysis" }));
    expect(set).toHaveBeenLastCalledWith("ai.send_gps", true);
  });

  it("rename commits on Enter and Escape keeps the name", () => {
    const rename = vi.fn();
    render(<ProjectSettingsView {...base} onRename={rename} />);
    const name = screen.getByLabelText("Name");
    fireEvent.change(name, { target: { value: "Costa Rica" } });
    fireEvent.keyDown(name, { key: "Escape" });
    expect(name).toHaveValue("Costa Rica 2026");
    fireEvent.change(name, { target: { value: "Costa Rica · family" } });
    fireEvent.blur(name);
    expect(rename).toHaveBeenCalledWith("Costa Rica · family");
  });

  it("devices, trip context and storage", () => {
    const clocks = vi.fn();
    render(<ProjectSettingsView {...base} onCheckClocks={clocks} />);
    const devices = within(screen.getByRole("region", { name: "Devices" }));
    expect(devices.getByText("Clock as recorded")).toBeInTheDocument();
    expect(devices.getByText(/LUT DJI_D-Log_M_to_Rec709.cube/)).toBeInTheDocument();
    fireEvent.click(devices.getByRole("button", { name: /Check camera clocks/ }));
    expect(clocks).toHaveBeenCalled();
    expect(within(screen.getByRole("region", { name: "Trip context" })).getByText(/Jul 14–24, 2026 · 2 days · 1 person · 2 must-include/)).toBeInTheDocument();
    const storage = within(screen.getByRole("region", { name: "Storage" }));
    expect(storage.getByText("19 GB")).toBeInTheDocument();
    expect(storage.getByText("Frees 15 GB")).toBeInTheDocument();
    expect(storage.getAllByText("Kept")).toHaveLength(3);
    expect(storage.getAllByText("Regenerable")).toHaveLength(2);
  });

  it("clearing asks first and says what is kept", () => {
    const clear = vi.fn();
    render(<ProjectSettingsView {...base} onClear={clear} />);
    fireEvent.click(screen.getByRole("button", { name: /Clear regenerable files/ }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText("Kept: ratings, notes and decisions, the AI analysis, frames and contact sheets, edits and renders.")).toBeInTheDocument();
    expect(dialog.getByText(/Previews are made again the next time you analyze/)).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Clear 15 GB" }));
    expect(clear).toHaveBeenCalled();
  });

  it("removal is never possible without the name (e.g. while it loads)", () => {
    render(<ProjectSettingsView {...base} name="" initialDialog="remove" />);
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" })).toBeDisabled();
  });

  it("removal needs the exact name", () => {
    const remove = vi.fn();
    render(<ProjectSettingsView {...base} onRemove={remove} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove…" }));
    const dialog = within(screen.getByRole("dialog"));
    const go = dialog.getByRole("button", { name: "Remove" });
    expect(go).toBeDisabled();
    fireEvent.change(dialog.getByLabelText("Type “Costa Rica 2026” to confirm"), { target: { value: "Costa Rica" } });
    expect(go).toBeDisabled();
    fireEvent.change(dialog.getByLabelText("Type “Costa Rica 2026” to confirm"), { target: { value: "Costa Rica 2026" } });
    fireEvent.click(go);
    expect(remove).toHaveBeenCalledWith("Costa Rica 2026");
  });

  it("read-only and loading states", () => {
    const { rerender } = render(<ProjectSettingsView {...base} readOnly />);
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    for (const r of screen.getAllByRole("radio")) expect(r).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Use GPS for analysis" })).toBeDisabled();
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Clear regenerable files/ })).toBeDisabled();
    rerender(<ProjectSettingsView {...base} settings={undefined} storage={undefined} devices={undefined} context={undefined} />);
    expect(screen.getByLabelText("Loading settings")).toBeInTheDocument();
    expect(screen.getByLabelText("Loading storage")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ screen

const calls: { method: string; path: string; body?: unknown }[] = [];
let removeStatus = 200;
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => {
      const data: Record<string, unknown> = {
        "/api/projects": { items: [{ id: "P1", name: "Costa Rica 2026", folder: { root: null, path: "/trips/cr" }, placement: "in_folder", fs_class: "local" }] },
        "/api/projects/{pid}/settings": { settings: SETTINGS },
        "/api/projects/{pid}/devices": { devices: DEVICES },
        "/api/projects/{pid}/trip-context": CONTEXT,
        "/api/projects/{pid}/storage": STORAGE,
      };
      return Promise.resolve(path in data ? { data: data[path] } : { error: { detail: "x" } });
    },
    PATCH: (path: string, o: { body: unknown }) => {
      calls.push({ method: "PATCH", path, body: o.body });
      return Promise.resolve({ data: {} });
    },
    POST: (path: string) => {
      calls.push({ method: "POST", path });
      return Promise.resolve({ data: { job_id: 4 }, response: { status: 202 } });
    },
    DELETE: (path: string, o: { body: unknown }) => {
      calls.push({ method: "DELETE", path, body: o.body });
      return Promise.resolve(removeStatus === 200 ? { data: {}, response: { status: 200 } } : { error: { detail: "the project is open in MosAic elsewhere" }, response: { status: 409 } });
    },
  },
}));

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/settings"]}>
        <Routes>
          <Route element={<Outlet context={{ readOnly: false }} />}>
            <Route path="/p/:pid/settings" element={<ProjectSettingsScreen />} />
          </Route>
          <Route path="/" element={<p>home</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("ProjectSettingsScreen saves settings, renames, clears and removes", async () => {
  calls.length = 0;
  removeStatus = 409;
  mount();
  expect(await screen.findByText("/trips/cr")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "Quick" }));
  await waitFor(() => expect(calls).toContainEqual({ method: "PATCH", path: "/api/projects/{pid}/settings", body: { values: { "analysis.mode": "quick" } } }));
  const name = screen.getByLabelText("Name");
  fireEvent.change(name, { target: { value: "CR" } });
  fireEvent.blur(name);
  await waitFor(() => expect(calls).toContainEqual({ method: "PATCH", path: "/api/projects/{pid}", body: { name: "CR" } }));
  fireEvent.click(screen.getByRole("button", { name: /Clear regenerable files/ }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^Clear / }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/projects/{pid}/storage/clear-cache")).toBe(true));
  // A refused removal says why and stays.
  fireEvent.click(screen.getByRole("button", { name: "Remove…" }));
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: "Costa Rica 2026" } });
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  expect(screen.queryByText("home")).toBeNull();
  await waitFor(() => expect(useToasts.getState().items.at(-1)?.message).toMatch(/open in MosAic elsewhere \(another window/));
  // Accepted: back to Home.
  removeStatus = 200;
  fireEvent.click(screen.getByRole("button", { name: "Remove…" }));
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: "Costa Rica 2026" } });
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" }));
  expect(await screen.findByText("home")).toBeInTheDocument();
});
