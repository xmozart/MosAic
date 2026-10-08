import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { EditsScreen } from "./EditsScreen";
import { EditsView, type EditsViewProps } from "./EditsView";
import { CARDS, ESTIMATE, PRESETS, card } from "./fixtures";
import { DEFAULT_REQUEST, defaultName, estimateText, lengthLabel, startFromChips, summaryLines, type EditRequest } from "./model";
import { WizardScreen } from "./WizardScreen";
import { WizardView, type WizardViewProps } from "./WizardView";

const noop = () => {};

describe("edit model", () => {
  it("the summary is made from the request alone (S14 acceptance)", () => {
    const req: EditRequest = { ...DEFAULT_REQUEST, duration_s: 300, aspect: "9:16", resolution: "4k", fps: "30000/1001", chronology: "strict" };
    expect(summaryLines(req, PRESETS)).toEqual([
      "5-minute cinematic journey",
      "9:16 · 4K · 29.97 fps",
      "Strict",
      "Balanced pace · about 3.5 s per shot",
      "Length within ±15 s",
    ]);
    const strict = summaryLines({ ...req, duration_s: 60, tolerance_pct: 0, fps: null, instructions: "End on the best sunset." }, PRESETS);
    expect(strict[0]).toBe("60-second cinematic journey");
    expect(strict[1]).toBe("9:16 · 4K · native frame rate");
    expect(strict).toContain("Strict length");
    expect(strict.at(-1)).toBe("Notes: End on the best sunset.");
  });

  it("names, lengths and the estimate read as the mockup does", () => {
    expect(defaultName("Costa Rica", { duration_s: 300, story: "cinematic_journey" })).toBe("Costa Rica — 5 min cinematic");
    expect(defaultName("Costa Rica", { duration_s: 60, story: "high_energy_montage" })).toBe("Costa Rica — 60 s montage");
    expect([15, 90, 120, 150, 1200, 5400].map(lengthLabel)).toEqual(["15 s", "90 s", "2 min", "2:30", "20 min", "1 h 30 min"]);
    expect(estimateText(ESTIMATE)).toBe("About 2 min · ~$0.25–0.55");
    expect(estimateText({ ...ESTIMATE, reuses_plan: true })).toBe("A few seconds · no AI cost");
    expect(estimateText({ ...ESTIMATE, cost_usd: null })).toBe("About 2 min · AI cost unknown");
  });

  it("start-from chips duplicate the newest edit and verticalize the newest landscape one", () => {
    const chips = startFromChips(CARDS);
    expect(chips.map((c) => c.label)).toEqual([
      "Duplicate “Costa Rica — 5 min cinematic” as 90 s",
      "Vertical version of “Costa Rica — 5 min cinematic”",
    ]);
    expect(startFromChips([card(9, { latest_version: null, status: "generating" })])).toEqual([]);
  });
});

const editsBase: EditsViewProps = {
  items: CARDS,
  coverUrl: (i) => `/f/${i}`,
  renderLink: (e, children, className) => (
    <a href={`#${e.edit_id}`} className={className}>
      {children}
    </a>
  ),
  onCreate: noop,
  onStartFrom: noop,
  now: new Date("2026-07-26T18:00:00"),
};

describe("EditsView", () => {
  it("cards show format, versions, status, progress and the preliminary warning", () => {
    render(<EditsView {...editsBase} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(4);
    const first = within(links[0]!);
    expect(first.getByText("Costa Rica — 5 min cinematic")).toBeInTheDocument();
    expect(first.getByText("16:9 · 4K")).toBeInTheDocument();
    expect(first.getByText("3 versions")).toBeInTheDocument();
    expect(first.getByText("Final rendered")).toBeInTheDocument();
    expect(first.getByText("5:02")).toBeInTheDocument();
    expect(first.getByText("Created Today 14:20")).toBeInTheDocument();
    expect(within(links[1]!).getByText("Preview ready")).toBeInTheDocument();
    expect(links[1]!.querySelector("img")!.className).toContain("aspect-[9/16]");
    expect(within(links[2]!).getByText("Generating… 64%")).toBeInTheDocument();
    expect(within(links[2]!).getByRole("img", { name: "64%" })).toBeInTheDocument();
    expect(within(links[3]!).getByText(/Made before analysis finished/)).toBeInTheDocument();
    expect(within(links[3]!).getByText("Preliminary")).toBeInTheDocument();
    expect(within(links[3]!).getByText("Created Jul 20")).toBeInTheDocument();
  });

  it("empty, loading and failed states; Create and Start from", () => {
    const create = vi.fn();
    const start = vi.fn();
    const { rerender } = render(<EditsView {...editsBase} items={[]} onCreate={create} />);
    expect(screen.getByText("Create your first edit")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Create edit" })[1]!);
    expect(create).toHaveBeenCalled();
    rerender(<EditsView {...editsBase} items={undefined} />);
    expect(screen.getByLabelText("Loading edits")).toBeInTheDocument();
    const retry = vi.fn();
    rerender(<EditsView {...editsBase} items={undefined} error onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    rerender(<EditsView {...editsBase} onStartFrom={start} />);
    fireEvent.click(screen.getByRole("button", { name: /Vertical version of/ }));
    expect(start.mock.calls[0]![0]).toMatchObject({ kind: "vertical", from: { edit_id: CARDS[0]!.edit_id } });
  });
});

function Wizard(p: Partial<WizardViewProps> & { onRequest?: (r: EditRequest) => void }) {
  const start: EditRequest = { ...DEFAULT_REQUEST, duration_s: 300 };
  const props: WizardViewProps = {
    step: 1,
    onStep: noop,
    request: start,
    onChange: (patch) => p.onRequest?.({ ...start, ...patch }),
    title: "Costa Rica — 5 min cinematic",
    presets: PRESETS,
    collages: { cinematic_journey: ["/a", "/b", "/c"] },
    estimate: ESTIMATE,
    creating: false,
    onCreate: noop,
    onWait: noop,
    ...p,
  };
  return <WizardView {...props} />;
}

describe("WizardView", () => {
  it("step 1: length, strict length, shape and more options change the request", () => {
    const seen: EditRequest[] = [];
    render(<Wizard onRequest={(r) => seen.push(r)} />);
    fireEvent.click(screen.getByRole("radio", { name: "90 s" }));
    expect(seen.at(-1)!.duration_s).toBe(90);
    fireEvent.click(screen.getByRole("switch", { name: /Strict length/ }));
    expect(seen.at(-1)!.tolerance_pct).toBe(0);
    expect(screen.getByText("Otherwise ±15 s")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "9:16" }));
    expect(seen.at(-1)!.aspect).toBe("9:16");
    expect(screen.getByRole("radio", { name: "Native" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /More options: resolution 1080p/ }));
    fireEvent.click(screen.getByRole("radio", { name: "4K" }));
    expect(seen.at(-1)!.resolution).toBe("4k");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "25" } });
    expect(seen.at(-1)!.fps).toBe("25");
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    fireEvent.change(screen.getByLabelText("Length in seconds"), { target: { value: "75" } });
    expect(seen.at(-1)!.duration_s).toBe(75);
  });

  it("the summary panel follows the request, and later steps wait for M4", () => {
    render(<Wizard />);
    const panel = within(screen.getByRole("complementary", { name: "Your edit" }));
    expect(panel.getByText("5-minute cinematic journey")).toBeInTheDocument();
    expect(panel.getByText("About 2 min · ~$0.25–0.55")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /What to feature/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Sound/ })).toBeDisabled();
  });

  it("step 2: a featured story, Custom's other stories, and chronology", () => {
    const seen: EditRequest[] = [];
    render(<Wizard step={2} onRequest={(r) => seen.push(r)} />);
    expect(screen.getAllByRole("radio", { name: /Cinematic journey|Wildlife|Custom/ })).toHaveLength(3);
    fireEvent.click(screen.getByRole("radio", { name: "Wildlife" }));
    expect(seen.at(-1)!.story).toBe("wildlife");
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    fireEvent.click(screen.getByRole("radio", { name: "Road trip" }));
    expect(seen.at(-1)!.story).toBe("road_trip");
    fireEvent.click(screen.getByRole("radio", { name: "Thematic" }));
    expect(seen.at(-1)!.chronology).toBe("thematic");
  });

  it("step 6: instructions and idea chips; ⌘Enter creates and ⌘↓ moves on", () => {
    const seen: EditRequest[] = [];
    const create = vi.fn();
    const step = vi.fn();
    render(<Wizard step={6} onRequest={(r) => seen.push(r)} onCreate={create} onStep={step} />);
    fireEvent.click(screen.getByRole("button", { name: "End on the best sunset" }));
    expect(seen.at(-1)!.instructions).toBe("End on the best sunset.");
    fireEvent.change(screen.getByLabelText("Instructions for the editor"), { target: { value: "Keep it calm." } });
    expect(seen.at(-1)!.instructions).toBe("Keep it calm.");
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(create).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "ArrowUp", metaKey: true });
    expect(step).toHaveBeenLastCalledWith(2);
  });

  it("⌘↓ moves to the next open step; arrows move within a choice group", () => {
    const step = vi.fn();
    const seen: EditRequest[] = [];
    render(<Wizard step={2} onStep={step} onRequest={(r) => seen.push(r)} />);
    fireEvent.keyDown(window, { key: "ArrowDown", metaKey: true });
    expect(step).toHaveBeenLastCalledWith(6); // steps 3–5 are skipped
    const first = screen.getByRole("radio", { name: "Cinematic journey" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(seen.at(-1)!.story).toBe("chronological_diary");
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Chronological diary" }));
  });

  it("preliminary banner, short footage warning, and nothing to edit", () => {
    const create = vi.fn();
    const wait = vi.fn();
    const { rerender } = render(<Wizard estimate={{ ...ESTIMATE, preliminary: true, analysis_pct: 42 }} onCreate={create} onWait={wait} />);
    expect(screen.getByText(/Analysis is 42% done/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create now (preliminary)" }));
    fireEvent.click(screen.getByRole("button", { name: "Wait" }));
    expect(create).toHaveBeenCalled();
    expect(wait).toHaveBeenCalled();
    rerender(<Wizard estimate={{ ...ESTIMATE, enough_footage: false, usable_seconds: 200 }} />);
    expect(screen.getByText(/adds up to about 3:20 — shorter than 5:00/)).toBeInTheDocument();
    const blocked = vi.fn();
    rerender(<Wizard estimate={{ ...ESTIMATE, candidates: 0 }} onCreate={blocked} />);
    expect(screen.getByText(/Nothing to edit yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create edit" })).toBeDisabled();
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(blocked).not.toHaveBeenCalled(); // ⌘Enter never gets around the disabled button
    rerender(<Wizard estimatePending />);
    expect(screen.getByText("About 2 min · ~$0.25–0.55")).toHaveAttribute("aria-busy", "true");
    rerender(<Wizard estimate={undefined} />);
    expect(screen.getByLabelText("Estimating")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ screens

const posts: { path: string; body: unknown }[] = [];
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => {
      if (path === "/api/projects") return Promise.resolve({ data: { items: [{ id: "P1", name: "Costa Rica" }] } });
      if (path === "/api/projects/{pid}/edits") return Promise.resolve({ data: { items: CARDS } });
      if (path === "/api/projects/{pid}/presets") return Promise.resolve({ data: { items: PRESETS } });
      if (path.endsWith("/collage")) return Promise.resolve({ data: { frames: [1, 2, 3] } });
      return Promise.resolve({ error: { detail: "unknown" } });
    },
    POST: (path: string, o: { body: unknown }) => {
      posts.push({ path, body: o.body });
      if (path === "/api/edits/estimate") return Promise.resolve({ data: ESTIMATE });
      return Promise.resolve({ data: { edit_id: "01JNEW", job_id: 7 } });
    },
  },
}));

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

function mount(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/p/:pid/edits" element={<EditsScreen />} />
          <Route path="/p/:pid/edits/new" element={<WizardScreen />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("EditsScreen lists the cards; Start from opens the wizard prefilled", async () => {
  mount("/p/P1/edits");
  expect(await screen.findByText("Wildlife cut")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Wildlife cut/ })).toHaveAttribute("href", `/p/P1/edits/${CARDS[2]!.edit_id}`);
  fireEvent.click(screen.getByRole("button", { name: /Vertical version of/ }));
  // The wizard opens with the source edit's request and the vertical shape.
  const panel = within(await screen.findByRole("complementary", { name: "Your edit" }));
  expect(await panel.findByText("9:16 · 1080p · native frame rate")).toBeInTheDocument();
  expect(panel.getByText("Costa Rica — 5 min cinematic")).toBeInTheDocument();
});

it("a cold Start from link waits for the source edit, and its odd length opens as custom", async () => {
  posts.length = 0;
  mount(`/p/P1/edits/new?from=${CARDS[1]!.edit_id}&aspect=bogus`);
  expect(screen.getByLabelText("Loading the edit to start from")).toBeInTheDocument();
  const panel = within(await screen.findByRole("complementary", { name: "Your edit" }));
  expect(panel.getByText("60-second high-energy montage")).toBeInTheDocument();
  expect(panel.getByText("9:16 · 1080p · native frame rate")).toBeInTheDocument(); // a bad ?aspect= is ignored
  await waitFor(() => expect(posts.some((p) => p.path === "/api/edits/estimate")).toBe(true));
  expect(posts.every((p) => (p.body as { request: EditRequest }).request.story === "high_energy_montage")).toBe(true);
});

it("a prefilled length that is not a chip shows as custom", () => {
  render(<WizardView {...{ step: 1, onStep: noop, request: { ...DEFAULT_REQUEST, duration_s: 75 }, onChange: noop, title: "t", presets: PRESETS, collages: {}, estimate: ESTIMATE, creating: false, onCreate: noop, onWait: noop }} />);
  expect(screen.getByRole("radio", { name: "Custom" })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByLabelText("Length in seconds")).toHaveValue(75);
});

it("WizardScreen estimates the request (debounced) and creates the edit", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  posts.length = 0;
  mount("/p/P1/edits/new");
  expect(await screen.findByText("Costa Rica — 3 min cinematic")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "60 s" }));
  fireEvent.click(screen.getByRole("radio", { name: "90 s" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });
  await waitFor(() => expect(posts.filter((p) => p.path === "/api/edits/estimate").at(-1)?.body).toMatchObject({ project_id: "P1", request: { duration_s: 90 } }));
  expect(posts.filter((p) => p.path === "/api/edits/estimate").some((p) => (p.body as { request: EditRequest }).request.duration_s === 60)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Create edit" }));
  expect(await screen.findByRole("heading", { name: "Edits" })).toBeInTheDocument();
  const created = posts.find((p) => p.path === "/api/projects/{pid}/edits")!.body as { request: EditRequest; name: string };
  expect(created.name).toBe("Costa Rica — 90 s cinematic");
  expect(created.request).toMatchObject({ duration_s: 90, aspect: "16:9", story: "cinematic_journey" });
  vi.useRealTimers();
});
