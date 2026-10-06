import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { DETAIL, GROUPS, item, page } from "./fixtures";
import { buildRows, gridLayout, headerText, MAX_TILES, MIN_TILE, wantsMoreAt } from "./layout";
import { LibraryScreen } from "./LibraryScreen";
import { aiVersusYou, optimistic } from "./model";
import { useLibraryView } from "./store";

type Opts = { body?: unknown; params?: { path?: Record<string, unknown>; query?: Record<string, unknown> } };
const calls: { method: string; path: string; opts?: Opts }[] = [];
let libraryReply: (q: Record<string, unknown>) => unknown = () => page();
const reply = (method: string, path: string, opts?: Opts) => {
  calls.push({ method, path, opts });
  if (path === "/api/projects/{pid}/library") return Promise.resolve({ data: libraryReply(opts?.params?.query ?? {}) });
  if (path === "/api/projects/{pid}/clips/{aid}") return Promise.resolve({ data: DETAIL });
  if (path === "/api/media/{pid}/filmstrip/{aid}") return Promise.resolve({ data: { frames: [] } });
  if (method !== "GET") return new Promise((r) => setTimeout(() => r({ data: {} }), 50));
  return Promise.resolve({ error: { detail: "unmocked" } });
};
vi.mock("@/api/client", () => ({
  api: {
    GET: (p: string, o?: Opts) => reply("GET", p, o),
    POST: (p: string, o?: Opts) => reply("POST", p, o),
    PATCH: (p: string, o?: Opts) => reply("PATCH", p, o),
  },
}));

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/library"]}>
        <Routes>
          <Route path="/p/:pid/library" element={<LibraryScreen />} />
          <Route path="/p/:pid/clips/:aid" element={<p>clip page</p>} />
          <Route path="/p/:pid/search" element={<p>search page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls.length = 0;
  libraryReply = () => page();
  useLibraryView.setState({ pid: null });
});

describe("library model", () => {
  it("an owner decision shows as the owner's at once; never include reads REJECT", () => {
    const it = item(0);
    expect(optimistic(it, { disposition: "MAYBE" })).toMatchObject({ status_shown: "MAYBE", decided_by: "user" });
    expect(optimistic(it, { include: "never" })).toMatchObject({ status_shown: "REJECT", decided_by: "user" });
    expect(optimistic(it, { stars: 4 })).toMatchObject({ status_shown: "USE", decided_by: "ai" }); // stars are not a disposition
    expect(optimistic(it, { add_tags: ["b", "a"] }).decision.tags).toEqual(["a", "b"]);
    expect(aiVersusYou({ ai_status: "USE", decision: { ...it.decision, disposition: "USE", stars: 4 } })).toBe("AI suggested USE · You: USE · You rated ★★★★");
  });

  it("rows put each group's header before its tiles, and skip collapsed groups", () => {
    const items = page().items;
    const rows = buildRows(GROUPS, items, 4, new Set());
    expect(rows.map((r) => (r.kind === "header" ? `H${r.group.key}` : r.items.length))).toEqual(["H2026-07-15", 4, 4, "H2026-07-16", 4]);
    expect(buildRows(GROUPS, items, 4, new Set(["2026-07-15"])).length).toBe(3);
    expect(headerText(GROUPS[0]!)).toEqual({ title: "Day 2 · Arenal / La Fortuna waterfall", facts: "8 clips · 41 m" });
    expect(headerText(GROUPS[1]!).title).toBe("Day 3 · Jul 16");
  });
});

describe("paging", () => {
  it("asks for more at the first expanded group with clips still to load, never for collapsed ones", () => {
    const partial = page(4).items; // 4 of Day 2's 8 clips loaded
    const rows = buildRows(GROUPS, partial, 4, new Set());
    expect(rows.map((r) => (r.kind === "header" ? `H${r.group.key}` : r.items.length))).toEqual(["H2026-07-15", 4, "H2026-07-16"]);
    expect(wantsMoreAt(rows, new Set())).toBe(1); // Day 2's last loaded row
    const day2Collapsed = new Set(["2026-07-15"]);
    expect(wantsMoreAt(buildRows(GROUPS, partial, 4, day2Collapsed), day2Collapsed)).toBe(1); // Day 3's header
    const allCollapsed = new Set(GROUPS.map((g) => g.key));
    expect(wantsMoreAt(buildRows(GROUPS, partial, 4, allCollapsed), allCollapsed)).toBeNull();
  });
});

describe("grid layout", () => {
  it("never mounts more than 60 tiles, at any common size, in either density", () => {
    for (const density of ["comfortable", "compact"] as const) {
      for (const width of [1280, 1440, 1680, 1920, 2560]) {
        for (const height of [700, 900, 1080, 1440]) {
          const l = gridLayout(width - 72 - 48, height - 120, density);
          expect(l.mountedTiles).toBeLessThanOrEqual(MAX_TILES);
          expect(l.tileW).toBeGreaterThanOrEqual(MIN_TILE[density] - 1);
        }
      }
    }
  });
});

describe("LibraryScreen", () => {
  it("decides with keys: optimistic user style, then the PATCH", async () => {
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    fireEvent.click(within(tiles[0]!).getByRole("button", { name: "CLIP_0001.MP4" }));
    fireEvent.keyDown(tiles[0]!, { key: "r" });
    // The chip turns into the owner's REJECT before the server answers.
    await waitFor(() => expect(within(screen.getAllByTestId("clip-tile")[0]!).getByText("REJECT")).toBeInTheDocument());
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.opts?.params?.path).toEqual({ pid: "P1", aid: 1 });
    expect(patch.opts?.body).toEqual({ disposition: "REJECT" });
    fireEvent.keyDown(tiles[0]!, { key: "4" });
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").at(-1)?.opts?.body).toEqual({ stars: 4 }));
  });

  it("shift-click selects a range and the BulkBar applies one change to all", async () => {
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    fireEvent.click(within(tiles[0]!).getByRole("button", { name: "CLIP_0001.MP4" }));
    fireEvent.click(within(tiles[2]!).getByRole("button", { name: "CLIP_0003.MP4" }), { shiftKey: true });
    const bar = await screen.findByRole("toolbar", { name: "3 clips selected" });
    fireEvent.click(within(bar).getByRole("button", { name: /Always/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.opts?.body).toEqual({ asset_ids: [1, 2, 3], include: "always" });
    fireEvent.keyDown(tiles[0]!, { key: "Escape" });
    expect(screen.queryByRole("toolbar", { name: /selected/ })).toBeNull();
  });

  it("shows rejected on request, and an empty filter offers to clear it", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Show rejected (2)" }));
    await waitFor(() => expect(calls.some((c) => c.opts?.params?.query?.show_rejected === true && c.opts.params.query.limit === 120)).toBe(true));
    libraryReply = (q) => (q.has_speech ? page(0, { rejected_hidden: 0 }) : page());
    fireEvent.keyDown(screen.getByRole("button", { name: /Has speech/ }), { key: "Enter" }); // Radix opens menus on keydown
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "Has speech" }));
    expect(await screen.findByText("No clips match.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findAllByTestId("clip-tile")).not.toHaveLength(0);
  });

  it("mounts only the visible rows of a long trip", async () => {
    libraryReply = () => ({ ...page(0), items: Array.from({ length: 5000 }, (_, i) => item(i, { group: "2026-07-15" })), groups: [{ ...GROUPS[0]!, count: 5000, clips: 5000 }] });
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    expect(tiles.length).toBeGreaterThan(0);
    expect(tiles.length).toBeLessThanOrEqual(60); // S10 acceptance: ≤ 60 tiles mounted
  });

  it("/ focuses search and Enter runs it", async () => {
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    fireEvent.keyDown(tiles[0]!, { key: "/" });
    const box = screen.getByLabelText("Search footage");
    expect(document.activeElement).toBe(box);
    fireEvent.change(box, { target: { value: "toucan" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(await screen.findByText("search page")).toBeInTheDocument();
  });
});


describe("LibraryScreen keys and focus", () => {
  it("Enter and Space on toolbar buttons are theirs, not the grid's", async () => {
    mount();
    await screen.findAllByTestId("clip-tile");
    const create = screen.getByRole("button", { name: /Create edit/ });
    fireEvent.keyDown(create, { key: "Enter" });
    fireEvent.keyDown(create, { key: " " });
    fireEvent.keyDown(create, { key: "r" });
    expect(screen.queryByText("clip page")).toBeNull();
    await new Promise((r) => setTimeout(r, 80));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("Tab to a tile and Enter opens that clip", async () => {
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    const third = within(tiles[2]!).getByRole("button", { name: "CLIP_0003.MP4" });
    expect(third).toHaveAttribute("tabindex", "-1");
    fireEvent.focus(third);
    await waitFor(() => expect(third).toHaveAttribute("tabindex", "0")); // roving tabindex
    fireEvent.keyDown(third, { key: "Enter" });
    expect(await screen.findByText("clip page")).toBeInTheDocument();
  });

  it("keys keep working after the focused tile scrolls out of the virtual window", async () => {
    libraryReply = () => ({ ...page(0), items: Array.from({ length: 400 }, (_, i) => item(i, { group: "2026-07-15" })), groups: [{ ...GROUPS[0]!, count: 400, clips: 400 }] });
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    const first = within(tiles[0]!).getByRole("button", { name: "CLIP_0001.MP4" });
    fireEvent.click(first);
    first.focus();
    const gridEl = screen.getByTestId("library-grid");
    Object.defineProperty(gridEl, "scrollHeight", { configurable: true, value: 400 * 200 });
    gridEl.scrollTop = 4000;
    fireEvent.scroll(gridEl); // the wheel takes the first rows away
    await waitFor(() => expect(screen.queryByRole("button", { name: "CLIP_0001.MP4" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(gridEl), { timeout: 1000 });
    fireEvent.keyDown(gridEl, { key: "u" });
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.opts?.params?.path).toEqual({ pid: "P1", aid: 1 }));
    fireEvent.keyDown(gridEl, { key: "ArrowRight" });
    expect(useLibraryView.getState().focus).toBe(2);
  });

  it("the inspector shows the owner's decision before the server answers", async () => {
    mount();
    const tiles = await screen.findAllByTestId("clip-tile");
    fireEvent.click(within(tiles[0]!).getByRole("button", { name: "CLIP_0001.MP4" }));
    const inspector = await screen.findByRole("complementary", { name: "Clip" });
    fireEvent.click(within(inspector).getByRole("radio", { name: /MAYBE/ }));
    await waitFor(() => expect(within(inspector).getByRole("radio", { name: /MAYBE/ })).toHaveAttribute("aria-checked", "true"));
    expect(within(inspector).getByText(/You: MAYBE/)).toBeInTheDocument();
  });
});


describe("LibraryScreen paging", () => {
  it("collapsing the loaded day still brings in the next one", async () => {
    libraryReply = (q) =>
      q.cursor ? { ...page(0), items: page(12).items.slice(8), groups: null, rejected_hidden: null } : { ...page(0), items: page(12).items.slice(0, 4), next_cursor: "c1" };
    mount();
    await screen.findAllByTestId("clip-tile");
    expect(screen.getByRole("button", { name: /Day 3/ })).toBeInTheDocument(); // header before its clips load
    fireEvent.click(screen.getByRole("button", { name: /Day 2/ }));
    await waitFor(() => expect(calls.some((c) => c.opts?.params?.query?.cursor === "c1")).toBe(true));
  });

  it("collapsing every day loads nothing more", async () => {
    libraryReply = (q) => (q.cursor ? page(0) : { ...page(0), items: page(12).items.slice(0, 4), next_cursor: "c1" });
    useLibraryView.setState({ pid: "P1", collapsed: GROUPS.map((g) => g.key), filters: {}, group: "day", showRejected: false, selection: [], focus: null });
    mount();
    await screen.findByRole("button", { name: /Day 3/ });
    await new Promise((r) => setTimeout(r, 100));
    expect(calls.some((c) => c.opts?.params?.query?.cursor === "c1")).toBe(false);
  });
});
