import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { card } from "@/features/edits/fixtures";
import type { RenderRow } from "@/lib/renders";

import { BEATS, EDIT, EVENTS, REPORT, renderRow } from "./fixtures";
import { beatAt, beatSegments, factsRows, timecode, toSource } from "./model";
import { PreviewScreen } from "./PreviewScreen";
import { PreviewView, type PreviewViewProps } from "./PreviewView";

const noop = () => {};

describe("preview model", () => {
  it("timeline positions become exact player times", () => {
    expect(toSource({ frames: 1724, rate: "30000/1001" })).toEqual({ ticks: 1724, tb: "1001/30000" });
    expect(timecode({ frames: 1800, rate: "30/1" })).toBe("1:00");
  });

  it("beats become bar segments, one per contiguous run", () => {
    const segs = beatSegments(EVENTS, BEATS);
    expect(segs.map((s) => s.label)).toEqual(["Arrival", "Into the jungle", "Wildlife", "Finale"]);
    expect(segs[0]).toMatchObject({ start: { ticks: 0 }, end: { ticks: 450 }, series: 1 });
    expect(segs[3]!.series).toBe(4);
    expect(beatAt(EVENTS, BEATS, 0)).toBe("Arrival");
    // runs follow beat ids, not titles; a shot outside every beat gets its own colour
    const twins = beatSegments(EVENTS.slice(0, 6), [BEATS[0]!, { ...BEATS[1]!, title: "Arrival" }]);
    expect(twins).toHaveLength(2);
    const loose = beatSegments([{ ...EVENTS[0]!, beat_id: null }], BEATS);
    expect(loose[0]).toMatchObject({ label: "Other", series: 5 });
    expect(beatAt(EVENTS, BEATS, 10_000)).toBeNull();
  });

  it("facts read as the mockup does", () => {
    expect(Object.fromEntries(factsRows(EDIT.facts))).toEqual({
      Duration: "1:00",
      Target: "1:00 ±3 s",
      Shots: "12",
      "Avg shot": "5.0 s",
      Beats: "4",
      Days: "9 of 11",
      Photos: "2",
      "AI cost": "$0.38",
    });
    expect(Object.fromEntries(factsRows({ ...EDIT.facts, tolerance: { frames: 0, rate: EDIT.rate }, ai_cost_usd: 0 }))).toMatchObject({
      Target: "1:00 exactly",
      "AI cost": "No AI cost",
    });
  });
});

const base: PreviewViewProps = {
  title: "Costa Rica — 5 min cinematic",
  state: { kind: "ready", edit: EDIT },
  versions: [1, 2, 3].map((v) => ({ version: v, created_at: "2026-07-26T14:20:00" })),
  onVersion: noop,
  preview: renderRow(2),
  previewUrl: "/preview.mp4",
  onRenderPreview: noop,
  onRenderFinal: noop,
  onRetryGenerate: noop,
  onBack: noop,
  onExports: noop,
  report: REPORT,
};

describe("PreviewView", () => {
  it("a shot's timecode seeks the player (S17 acceptance)", () => {
    render(<PreviewView {...base} />);
    const video = document.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 60, configurable: true });
    fireEvent.loadedMetadata(video);
    const shot = REPORT.events[2]!;
    fireEvent.click(screen.getByRole("button", { name: `Go to ${timecode(shot.timeline_in)}` }));
    // a quarter into the shot's first frame, at 29.97 fps
    expect(video.currentTime).toBeCloseTo((shot.timeline_in.frames + 0.25) * (1001 / 30000), 6);
    expect(document.activeElement).toBe(screen.getByLabelText("Player"));
  });

  it("player, facts, versions and the beat segments", () => {
    const onVersion = vi.fn();
    render(<PreviewView {...base} onVersion={onVersion} />);
    expect(screen.getByText("v3 · preview 720p")).toBeInTheDocument();
    expect(screen.getAllByTestId("segment")).toHaveLength(4);
    const facts = within(screen.getByRole("region", { name: "Edit facts" }));
    expect(facts.getByText("9 of 11")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "v1" }));
    expect(onVersion).toHaveBeenCalledWith(1);
    expect(screen.getByRole("button", { name: /Open storyboard/ })).toBeDisabled();
  });

  it("rendering, failed and missing preview states", () => {
    const again = vi.fn();
    const { rerender } = render(<PreviewView {...base} preview={renderRow(2, { status: "rendering", pct: 45 })} />);
    expect(screen.getByText("Rendering preview… 45%")).toBeInTheDocument();
    expect(document.querySelector("video")).toBeNull();
    rerender(<PreviewView {...base} preview={renderRow(2, { status: "failed" })} onRenderPreview={again} />);
    fireEvent.click(screen.getByRole("button", { name: "Render again" }));
    expect(again).toHaveBeenCalled();
    rerender(<PreviewView {...base} preview={undefined} />);
    expect(screen.getByRole("button", { name: "Render preview" })).toBeInTheDocument();
  });

  it("Render final, its progress, then Download final", () => {
    const final = vi.fn();
    const { rerender } = render(<PreviewView {...base} onRenderFinal={final} />);
    fireEvent.click(screen.getByRole("button", { name: "Render final" }));
    expect(final).toHaveBeenCalled();
    rerender(<PreviewView {...base} final={renderRow(3, { kind: "final", status: "rendering", pct: 20 })} />);
    expect(screen.getByRole("button", { name: "Rendering final…" })).toBeDisabled();
    expect(screen.getByText("Final: Rendering 20%")).toBeInTheDocument();
    rerender(<PreviewView {...base} final={renderRow(3, { kind: "final" })} finalDownloadUrl="/dl" />);
    expect(screen.getByRole("link", { name: /Download final/ })).toHaveAttribute("href", "/dl");
  });

  it("the report: reasons, not used, and rejections marked by who made them", () => {
    const more = vi.fn();
    render(<PreviewView {...base} onMoreRejected={more} />);
    const panel = within(screen.getByRole("complementary", { name: "Selection report" }));
    expect(panel.getAllByText("Strong opener: wide shot of the bay at sunrise.").length).toBeGreaterThan(0);
    fireEvent.click(panel.getByRole("radio", { name: "Not used 1" }));
    expect(panel.getByText(/the toucan is further away/)).toBeInTheDocument();
    fireEvent.click(panel.getByRole("radio", { name: "Rejected 3" }));
    expect(panel.getByLabelText("REJECT, set by you")).toBeInTheDocument();
    expect(panel.getByLabelText("REJECT, suggested by AI")).toBeInTheDocument();
    expect(panel.getByText("Whole clip")).toBeInTheDocument();
    expect(panel.getByText("Very shaky · Lens covered")).toBeInTheDocument();
    fireEvent.click(panel.getByRole("button", { name: "Show more (1 left)" }));
    expect(more).toHaveBeenCalled();
  });

  it("generating, failed and missing edit states", () => {
    const retry = vi.fn();
    const { rerender } = render(<PreviewView {...base} state={{ kind: "generating", pct: 64 }} />);
    expect(screen.getByText(/still being made \(64%\)/)).toBeInTheDocument();
    rerender(<PreviewView {...base} state={{ kind: "failed", error: "No usable clips." }} onRetryGenerate={retry} />);
    expect(screen.getByText(/We couldn't create this edit. No usable clips./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    rerender(<PreviewView {...base} state={{ kind: "missing" }} />);
    expect(screen.getByText(/can't find this edit/)).toBeInTheDocument();
    const make = vi.fn();
    rerender(<PreviewView {...base} state={{ kind: "new" }} onRetryGenerate={make} />);
    fireEvent.click(screen.getByRole("button", { name: "Make it now" }));
    expect(make).toHaveBeenCalled();
    const reload = vi.fn();
    rerender(<PreviewView {...base} state={{ kind: "error" }} onRetryLoad={reload} />);
    expect(screen.getByText("We couldn't load this edit.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reload).toHaveBeenCalled();
  });
});

// ------------------------------------------------------------------ screen

const posts: { path: string; body: unknown }[] = [];
const gets: { path: string; params?: { path?: Record<string, unknown>; query?: Record<string, unknown> } }[] = [];
let mode: "ready" | "failed" | "versions" = "ready";
/** Per version: the renders the server reports (the versions test changes them). */
const server: Record<number, RenderRow[]> = {};
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string, o?: { params?: { path?: Record<string, unknown>; query?: Record<string, unknown> } }) => {
      gets.push({ path, params: o?.params });
      if (path === "/api/projects/{pid}/edits")
        return Promise.resolve({ data: { items: [mode === "failed" ? card(1, { edit_id: EDIT.edit_id, latest_version: null, status: "failed", error: "No usable clips." }) : card(1, { edit_id: EDIT.edit_id, name: EDIT.name, latest_version: 3 })] } });
      if (path === "/api/edits/{eid}")
        return Promise.resolve(mode === "failed" ? { error: { detail: "x" }, response: { status: 404 } } : { data: { ...EDIT, renders: server[3] ?? [] }, response: { status: 200 } });
      if (path === "/api/edits/{eid}/versions/{version}") {
        const v = Number(o?.params?.path?.version);
        return Promise.resolve({ data: { ...EDIT, version: v, renders: server[v] ?? [] }, response: { status: 200 } });
      }
      if (path === "/api/edits/{eid}/versions") return Promise.resolve({ data: { items: [2, 3].map((v) => ({ version: v, created_at: "x" })) } });
      if (path === "/api/edits/{eid}/report") return Promise.resolve({ data: { ...REPORT, version: Number(o?.params?.query?.version) } });
      return Promise.resolve({ error: { detail: "unknown" }, response: { status: 404 } });
    },
    POST: (path: string, o: { body?: unknown }) => {
      posts.push({ path, body: o?.body });
      return Promise.resolve({ data: { render_id: 9, job_id: 1 } });
    },
  },
}));

afterEach(() => {
  vi.useRealTimers();
});

function mount(search = "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/p/P1/edits/${EDIT.edit_id}${search}`]}>
        <Routes>
          <Route path="/p/:pid/edits/:eid" element={<PreviewScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("PreviewScreen starts a preview once for a version without one, and renders the final", async () => {
  mode = "ready";
  posts.length = 0;
  delete server[3];
  mount();
  expect(await screen.findByText("Costa Rica — 5 min cinematic")).toBeInTheDocument();
  await waitFor(() => expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1));
  expect(posts[0]!.body).toEqual({ edit_id: EDIT.edit_id, version: 3, final: false });
  fireEvent.click(await screen.findByRole("button", { name: "Render final" }));
  await waitFor(() => expect(posts.at(-1)!.body).toEqual({ edit_id: EDIT.edit_id, version: 3, final: true }));
  expect(posts.filter((p) => (p.body as { final: boolean }).final === false)).toHaveLength(1);
});

it("PreviewScreen shows a failed edit and starts it again", async () => {
  mode = "failed";
  posts.length = 0;
  mount();
  expect(await screen.findByText(/We couldn't create this edit/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(posts.some((p) => p.path === "/api/edits/{eid}/generate")).toBe(true));
});

it("PreviewScreen follows ?v=: that version, its report, one preview each, and polls only while rendering", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mode = "versions";
  posts.length = 0;
  gets.length = 0;
  server[2] = [renderRow(5, { version: 2, status: "rendering", pct: 30 })];
  server[3] = [];
  mount("?v=2");
  expect(await screen.findByText("Rendering preview… 30%")).toBeInTheDocument();
  expect(gets.some((g) => g.path === "/api/edits/{eid}/versions/{version}" && g.params?.path?.version === 2)).toBe(true);
  await waitFor(() => expect(gets.some((g) => g.path === "/api/edits/{eid}/report" && g.params?.query?.version === 2)).toBe(true));
  expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(0); // v2 has a preview on the way
  // the render finishes: one more poll shows it, then polling stops
  server[2] = [renderRow(5, { version: 2 })];
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2100);
  });
  await waitFor(() => expect(screen.getByText(/v2 · preview 720p/)).toBeInTheDocument());
  const polls = () => gets.filter((g) => g.path === "/api/edits/{eid}/versions/{version}").length;
  const settled = polls();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(6000);
  });
  expect(polls()).toBe(settled);
  // switching to v3 (no preview) starts exactly one, for v3
  fireEvent.click(screen.getByRole("radio", { name: "v3" }));
  await waitFor(() => expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1));
  expect(posts[0]!.body).toEqual({ edit_id: EDIT.edit_id, version: 3, final: false });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1);
  vi.useRealTimers();
});
