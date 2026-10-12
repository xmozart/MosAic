import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { useToasts } from "@/lib/toasts";

import { COMPARE, VERSIONS } from "./fixtures";
import { changeText, defaultPair } from "./model";
import { VersionsScreen } from "./VersionsScreen";
import { VersionsView, type VersionsViewProps } from "./VersionsView";

const noop = () => {};
const RATE = "30000/1001";

describe("S18 model", () => {
  it("says what changed in words", () => {
    const [replaced, trimmed, moved, removed] = COMPARE.changes;
    expect(changeText(replaced!, RATE)).toBe("IMG_4390.MOV → DSC_0932.MOV");
    expect(changeText(trimmed!, RATE)).toBe("IMG_4472.MOV extended +1.2 s");
    expect(changeText({ ...trimmed!, frames_b: trimmed!.frames_a! - 24 }, RATE)).toBe("IMG_4472.MOV shortened −0.8 s");
    expect(changeText(moved!, RATE)).toBe("IMG_4512.HEIC → Finale");
    expect(changeText(removed!, RATE)).toBe("GX030214.MP4");
    expect(defaultPair(VERSIONS)).toEqual([2, 3]);
    expect(defaultPair(VERSIONS.slice(0, 1))).toBeNull();
  });
});

function View(p: Partial<VersionsViewProps>) {
  return (
    <VersionsView
      title="Costa Rica"
      versions={VERSIONS}
      pair={[2, 3]}
      compare={COMPARE}
      previews={{ 2: { url: "/a.mp4" }, 3: { url: "/b.mp4" } }}
      onSelect={noop}
      onLatestPair={noop}
      onRevert={noop}
      onBack={noop}
      now={new Date("2026-07-26T18:00:00")}
      {...p}
    />
  );
}

describe("S18 VersionsView", () => {
  it("lists versions newest first with who, why, when and how long", () => {
    render(<View />);
    const items = within(screen.getByRole("list", { name: "Versions" })).getAllByRole("button");
    expect(items.map((x) => x.textContent)).toEqual([
      expect.stringContaining("v3You5:02Applied: repetitionToday 14:12"),
      expect.stringContaining("v2AI5:04"),
      expect.stringContaining("v1AI4:57First edit from the wizard"),
    ]);
    expect(items[0]).toHaveAttribute("aria-pressed", "true");
    expect(items[2]).toHaveAttribute("aria-pressed", "false");
  });

  it("selects a version to compare, reverts to the older one, and seeks to a change", () => {
    const onSelect = vi.fn();
    const onRevert = vi.fn();
    render(<View onSelect={onSelect} onRevert={onRevert} />);
    fireEvent.click(screen.getByRole("button", { name: /^v1/ }));
    expect(onSelect).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: /Revert to v2/ }));
    expect(onRevert).toHaveBeenCalledWith(2);
    const changes = within(screen.getByRole("region", { name: "What changed" }));
    expect(changes.getAllByRole("listitem").map((x) => x.firstChild!.textContent)).toEqual(["Replaced", "Trimmed", "Moved", "Removed"]);
    const videos = Array.from(document.querySelectorAll("video"));
    for (const v of videos) {
      Object.defineProperty(v, "duration", { value: 400, configurable: true });
      fireEvent.loadedMetadata(v);
    }
    fireEvent.click(changes.getByRole("button", { name: "Go to 1:27 in v3" }));
    for (const v of videos) expect(v.currentTime).toBeCloseTo(Math.round((88 * 30000) / 1001) / (30000 / 1001), 3);
  });

  it("synced: playing one plays the other; independent: it doesn't", () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    render(<View />);
    const [left, right] = Array.from(document.querySelectorAll("video"));
    Object.defineProperty(right!, "paused", { value: true, configurable: true });
    fireEvent.play(left!);
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: "Independent" }));
    fireEvent.play(left!);
    expect(play).toHaveBeenCalledTimes(1);
    play.mockRestore();
  });

  it("synced: a seek and a pause follow, once; independent: they don't", () => {
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    render(<View />);
    const [left, right] = Array.from(document.querySelectorAll("video"));
    for (const v of [left!, right!]) {
      Object.defineProperty(v, "duration", { value: 400, configurable: true });
      fireEvent.loadedMetadata(v);
    }
    left!.currentTime = 10;
    fireEvent.seeked(left!);
    expect(right!.currentTime).toBe(10);
    // The right one's own seeked event: the left is already there, so it isn't moved again.
    let sets = 0;
    const proto = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "currentTime")!;
    Object.defineProperty(left!, "currentTime", {
      configurable: true,
      get: () => proto.get!.call(left),
      set: (x: number) => {
        sets += 1;
        proto.set!.call(left, x);
      },
    });
    fireEvent.seeked(right!);
    expect(sets).toBe(0);
    delete (left as unknown as Record<string, unknown>).currentTime;
    fireEvent.pause(left!);
    expect(pause).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: "Independent" }));
    left!.currentTime = 30;
    fireEvent.seeked(left!);
    expect(right!.currentTime).toBe(10);
    pause.mockRestore();
  });

  it("no Revert once the two are the same, nor when the pair isn't the latest", () => {
    const { rerender } = render(<View compare={{ ...COMPARE, a: 1, b: 4, same: true, changes: [] }} pair={[1, 4]} versions={[...VERSIONS, { ...VERSIONS[0]!, version: 4 }]} />);
    expect(screen.getByText("These two versions are the same.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revert/ })).toBeNull();
    rerender(<View pair={[1, 2]} compare={{ ...COMPARE, a: 1, b: 2 }} />);
    expect(screen.queryByRole("button", { name: /Revert/ })).toBeNull();
  });

  it("one version: nothing to compare yet", () => {
    render(<View versions={VERSIONS.slice(0, 1)} pair={null} compare={undefined} />);
    expect(screen.getByText(/This edit has one version so far/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Compare/ })).toBeNull();
  });
});

// ------------------------------------------------------------------ screen

const posts: { path: string; body?: unknown }[] = [];
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string, o?: { params?: { query?: Record<string, unknown>; path?: Record<string, unknown> } }) => {
      if (path === "/api/projects/{pid}/edits") return Promise.resolve({ data: { items: [] } });
      if (path === "/api/edits/{eid}/versions") return Promise.resolve({ data: { items: VERSIONS } });
      if (path === "/api/edits/{eid}/compare") return Promise.resolve({ data: { ...COMPARE, a: o!.params!.query!.a, b: o!.params!.query!.b } });
      if (path === "/api/edits/{eid}/versions/{version}") return Promise.resolve({ data: { renders: [] } });
      return Promise.resolve({ error: { detail: "x" } });
    },
    POST: (path: string, o: { body?: unknown }) => {
      posts.push({ path, body: o?.body });
      if (path === "/api/edits/{eid}/revert") return Promise.resolve({ data: { version: 4 } });
      return Promise.resolve({ data: { render_id: 1, job_id: 1 } });
    },
  },
}));

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

it("VersionsScreen compares the latest two, any version with the latest, and reverts", async () => {
  useToasts.setState({ items: [] });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/edits/E1/versions"]}>
        <Routes>
          <Route path="/p/:pid/edits/:eid/versions" element={<><VersionsScreen /><Where /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Compare v2 and v3" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^v1/ }));
  expect(await screen.findByRole("heading", { name: "Compare v1 and v3" })).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent("?a=1&b=3");
  fireEvent.click(screen.getAllByRole("button", { name: "Render preview" })[0]!);
  await waitFor(() => expect(posts.at(-1)).toEqual({ path: "/api/renders", body: { edit_id: "E1", version: 1, final: false, codec: "h264" } }));
  fireEvent.click(screen.getByRole("button", { name: /Revert to v1/ }));
  await waitFor(() => expect(posts.at(-1)).toEqual({ path: "/api/edits/{eid}/revert", body: { version: 1 } }));
  await waitFor(() => expect(useToasts.getState().items.map((x) => x.message)).toContain("Version 4 created, the same as v1."));
  expect(screen.getByTestId("where")).toHaveTextContent("?a=1&b=4");
});
