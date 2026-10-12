import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { card } from "@/features/edits/fixtures";
import type { RenderRow } from "@/lib/renders";
import { useToasts } from "@/lib/toasts";

import { BEATS, EDIT, EVENTS, EXPORT_OPTIONS, FINDINGS, REPORT, renderRow } from "./fixtures";
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

  it("title cards are their own segments, never a beat's or Other", () => {
    const card = { ...EVENTS[0]!, event_id: "evt_0000", kind: "title", asset_id: null, segment_id: null, beat_id: null };
    const segs = beatSegments([card, ...EVENTS.slice(0, 2)], BEATS);
    expect(segs.map((s) => s.label)).toEqual(["Title", "Arrival"]);
    expect(segs[0]!.series).toBe(6);
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
  onStoryboard: noop,
  onVersions: noop,
  report: REPORT,
  findings: FINDINGS,
  latest: true,
  onApplyFinding: noop,
  onIgnoreFinding: noop,
  onApplyAll: noop,
  onIgnoreAll: noop,
  onRegenerateWithFixes: noop,
};

describe("PreviewView", () => {
  it("a shot's timecode seeks the player (S17 acceptance)", () => {
    render(<PreviewView {...base} initialPanel="report" />);
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
    const onStoryboard = vi.fn();
    render(<PreviewView {...base} onVersion={onVersion} onStoryboard={onStoryboard} />);
    expect(screen.getByText("v3 · preview 720p")).toBeInTheDocument();
    expect(screen.getAllByTestId("segment")).toHaveLength(4);
    const facts = within(screen.getByRole("region", { name: "Edit facts" }));
    expect(facts.getByText("9 of 11")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "v1" }));
    expect(onVersion).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: /Open storyboard/ }));
    expect(onStoryboard).toHaveBeenCalled();
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

  it("findings: severity, fix, applied state, and Apply / Ignore / Regenerate with fixes", () => {
    const apply = vi.fn();
    const ignore = vi.fn();
    const all = vi.fn();
    const regen = vi.fn();
    render(<PreviewView {...base} onApplyFinding={apply} onIgnoreFinding={ignore} onApplyAll={all} onRegenerateWithFixes={regen} />);
    const panel = within(screen.getByRole("region", { name: "Findings" }));
    const cards = panel.getAllByRole("article");
    expect(cards).toHaveLength(5);
    expect(within(cards[0]!).getByText("Applied in v3")).toBeInTheDocument();
    expect(within(cards[0]!).queryByRole("button", { name: "Apply" })).toBeNull();
    expect(within(cards[1]!).getByText("Issue")).toBeInTheDocument();
    expect(within(cards[1]!).queryByRole("button", { name: "Apply" })).toBeNull(); // no fix: Ignore only
    expect(within(cards[2]!).getByText("Suggestion")).toBeInTheDocument();
    expect(within(cards[2]!).getByText("Replace it with GX010233.MP4")).toBeInTheDocument();
    fireEvent.click(within(cards[2]!).getByRole("button", { name: "Apply" }));
    fireEvent.click(within(cards[1]!).getByRole("button", { name: "Ignore" }));
    fireEvent.click(panel.getByRole("button", { name: "Apply all" }));
    fireEvent.click(panel.getByRole("button", { name: /Regenerate with fixes/ }));
    expect(apply).toHaveBeenCalledWith(FINDINGS[2]!.finding_id);
    expect(ignore).toHaveBeenCalledWith(FINDINGS[1]!.finding_id);
    expect(all).toHaveBeenCalled();
    expect(regen).toHaveBeenCalled();
    expect(panel.getByText("4")).toBeInTheDocument(); // open findings
  });

  it("findings: N / P move between them and seek, A applies the focused one", () => {
    const apply = vi.fn();
    render(<PreviewView {...base} onApplyFinding={apply} />);
    const video = document.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 600, configurable: true });
    fireEvent.loadedMetadata(video);
    fireEvent.keyDown(window, { key: "n" });
    fireEvent.keyDown(window, { key: "n" });
    fireEvent.keyDown(window, { key: "n" });
    expect(document.activeElement).toHaveAccessibleName(`Suggestion at ${timecode({ frames: FINDINGS[2]!.frame, rate: "30000/1001" })}`);
    expect(video.currentTime).toBeCloseTo((FINDINGS[2]!.frame + 0.25) * (1001 / 30000), 6);
    fireEvent.keyDown(window, { key: "a" });
    expect(apply).toHaveBeenCalledWith(FINDINGS[2]!.finding_id);
    fireEvent.keyDown(window, { key: "p" });
    fireEvent.keyDown(window, { key: "a" }); // no fix: nothing to apply
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("clicking a finding's timecode seeks the player (S17 acceptance)", () => {
    render(<PreviewView {...base} />);
    const video = document.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 600, configurable: true });
    fireEvent.loadedMetadata(video);
    const f = FINDINGS[3]!;
    fireEvent.click(screen.getByRole("button", { name: `Go to ${timecode({ frames: f.frame, rate: "30000/1001" })}` }));
    expect(video.currentTime).toBeCloseTo((f.frame + 0.25) * (1001 / 30000), 6);
  });

  it("findings: A applies only the finding that has the focus", () => {
    const apply = vi.fn();
    const { rerender } = render(<PreviewView {...base} onApplyFinding={apply} />);
    fireEvent.keyDown(window, { key: "n" });
    fireEvent.keyDown(window, { key: "n" });
    fireEvent.keyDown(window, { key: "n" }); // the shaky shot, which has a fix
    screen.getByRole("button", { name: "Render final" }).focus(); // focus moves away
    fireEvent.keyDown(window, { key: "a" });
    expect(apply).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "n" });
    fireEvent.keyDown(window, { key: "p" }); // back on it
    // A new list (the fix made a new version): the old focus counts for nothing.
    rerender(<PreviewView {...base} onApplyFinding={apply} findings={FINDINGS.map((f) => ({ ...f, finding_id: `${f.finding_id}x` }))} />);
    fireEvent.keyDown(window, { key: "a" });
    expect(apply).not.toHaveBeenCalled();
  });

  it("findings: none, and an older version's can't be applied", () => {
    const { rerender } = render(<PreviewView {...base} findings={[]} />);
    expect(screen.getByText("Looks good — no issues found")).toBeInTheDocument();
    rerender(<PreviewView {...base} latest={false} />);
    expect(screen.getByText(/Fixes apply to the latest version/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply all" })).toBeDisabled();
  });

  it("the report: reasons, not used, and rejections marked by who made them", () => {
    const more = vi.fn();
    render(<PreviewView {...base} onMoreRejected={more} />);
    fireEvent.click(screen.getByRole("radio", { name: "Why these shots" }));
    const panel = within(screen.getByRole("region", { name: "Selection report" }));
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
      if (path === "/api/edits/{eid}/export") return Promise.resolve({ data: EXPORT_OPTIONS });
      if (path === "/api/edits/{eid}/findings") return Promise.resolve({ data: { version: 3, items: FINDINGS } });
      if (path === "/api/jobs/{job_id}") return Promise.resolve({ data: { job_id: 11, state: "done", error: null } });
      if (path === "/api/edits/{eid}/report") return Promise.resolve({ data: { ...REPORT, version: Number(o?.params?.query?.version) } });
      return Promise.resolve({ error: { detail: "unknown" }, response: { status: 404 } });
    },
    POST: (path: string, o: { body?: unknown }) => {
      posts.push({ path, body: o?.body });
      if (path === "/api/edits/{eid}/findings/{fid}/apply" || path === "/api/edits/{eid}/findings/apply-all") return Promise.resolve({ data: { version: 4 } });
      if (path === "/api/edits/{eid}/findings/regenerate") return Promise.resolve({ data: { version: 4, job_id: 11, beats: ["b2", "b3"] } });
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
  expect(posts[0]!.body).toEqual({ edit_id: EDIT.edit_id, version: 3, final: false, codec: "h264" });
  fireEvent.click(await screen.findByRole("button", { name: "Render final" }));
  const dialog = await screen.findByRole("dialog", { name: "Render final" });
  fireEvent.click(await within(dialog).findByRole("radio", { name: /Master/ }));
  fireEvent.click(within(dialog).getByRole("checkbox", { name: /Edit data/ }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Render" }));
  await waitFor(() =>
    expect(posts.at(-1)!.body).toEqual({ edit_id: EDIT.edit_id, version: 3, final: true, codec: "prores", resolution: "4k", loudness: "web", sidecars: ["srt", "report", "edl"], save_to: null }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
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
  expect(posts[0]!.body).toEqual({ edit_id: EDIT.edit_id, version: 3, final: false, codec: "h264" });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1);
  vi.useRealTimers();
});

it("PreviewScreen applies a finding as a new version, with Undo reverting to the one before", async () => {
  mode = "ready";
  posts.length = 0;
  server[3] = [renderRow(5, { version: 3 })];
  useToasts.setState({ items: [] });
  mount();
  const card = (await screen.findAllByRole("article"))[2]!;
  fireEvent.click(within(card).getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(posts.map((p) => p.path)).toContain("/api/edits/{eid}/findings/{fid}/apply"));
  await waitFor(() => expect(useToasts.getState().items.map((x) => x.message)).toContain("Version 4 created"));
  useToasts.getState().items.find((x) => x.message === "Version 4 created")!.action!.run();
  await waitFor(() => expect(posts.at(-1)).toEqual({ path: "/api/edits/{eid}/revert", body: { version: 3 } }));
});

it("PreviewScreen's Regenerate with fixes applies them, then follows the beats' job", async () => {
  mode = "ready";
  posts.length = 0;
  gets.length = 0;
  server[3] = [renderRow(5, { version: 3 })];
  useToasts.setState({ items: [] });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /Regenerate with fixes/ }));
  await waitFor(() => expect(posts.map((p) => p.path)).toContain("/api/edits/{eid}/findings/regenerate"));
  await waitFor(() => expect(gets.some((g) => g.path === "/api/jobs/{job_id}")).toBe(true));
  await waitFor(() => expect(useToasts.getState().items.map((x) => x.message)).toContain("The regenerated version is ready."));
  const messages = useToasts.getState().items;
  expect(messages.map((x) => x.message)).toContain("Regenerating 2 beats that still have issues. Your locked shots stay.");
  // No Undo while the beats regenerate on top of the fixes.
  expect(messages.find((x) => x.message === "Fixes applied as version 4")!.action).toBeUndefined();
});
