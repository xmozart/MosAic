import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { useToasts } from "@/lib/toasts";

import { ALTERNATIVES, DRAFT } from "./fixtures";
import { beatFrames, beatLocked, moveBeatOp, moveShotOp, shotFrames, type DraftOp, type DraftState } from "./model";
import { StoryboardScreen } from "./StoryboardScreen";
import { StoryboardView, type StoryboardViewProps } from "./StoryboardView";

const noop = () => {};
const beats = DRAFT.board.beats;

describe("S16 model", () => {
  it("a dragged shot's index accounts for it leaving its place", () => {
    expect(moveShotOp(beats, "b1#0", "b1", 0)).toBeNull();
    expect(moveShotOp(beats, "b1#0", "b1", 1)).toBeNull(); // just after itself: no move
    expect(moveShotOp(beats, "b1#0", "b1", 3)).toEqual({ kind: "move_shot", ref: "b1#0", beat_id: "b1", index: 2 });
    expect(moveShotOp(beats, "b1#3", "b1", 0)).toEqual({ kind: "move_shot", ref: "b1#3", beat_id: "b1", index: 0 });
    expect(moveShotOp(beats, "b1#0", "b2", 2)).toEqual({ kind: "move_shot", ref: "b1#0", beat_id: "b2", index: 2 });
    expect(moveBeatOp(beats, "b1", 0)).toBeNull();
    expect(moveBeatOp(beats, "b1", 3)).toEqual({ kind: "move_beat", beat_id: "b1", index: 2 });
    expect(moveBeatOp(beats, "b4", 0)).toEqual({ kind: "move_beat", beat_id: "b4", index: 0 });
  });

  it("times shots and beats from the timeline; a beat is locked when all its shots are", () => {
    const shots = shotFrames(DRAFT);
    expect(shots.get("b1#0")).toBe(90);
    expect(shots.has("b1#6")).toBe(false); // dropped to fit
    expect(beatFrames(DRAFT).get("b1")).toBe([3, 5, 4, 6, 5, 4].reduce((n, s) => n + Math.round((s * 30000) / 1001), 0));
    expect(beatLocked(beats[3]!)).toBe(true);
    expect(beatLocked(beats[0]!)).toBe(false);
  });
});

function View(p: Partial<StoryboardViewProps> & { d?: Partial<DraftState> }) {
  const props: StoryboardViewProps = {
    draft: { ...DRAFT, ...p.d },
    frame: (sid) => `/f/${sid}`,
    alternatives: () => ALTERNATIVES,
    player: () => <p>playing</p>,
    warnings: {},
    onOp: noop,
    onUndo: noop,
    onRedo: noop,
    onSave: noop,
    onRegenerateBeat: noop,
    onRegenerateStory: noop,
    onPreview: noop,
    onChangeSettings: noop,
    ...p,
  };
  return <StoryboardView {...props} />;
}

/** jsdom has no DragEvent: a plain event with the pointer's x. */
function dragAt(el: Element, type: string, clientX: number) {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(e, { clientX, dataTransfer: { setData: noop, setDragImage: noop } });
  fireEvent(el, e);
}

const beat = (name: string) => screen.getByRole("region", { name });
const chip = (beatName: string, i: number) => within(beat(beatName)).getAllByRole("button", { name: /^\w+(, \d:\d\d)?(, locked)?$/ })[i]!;

describe("S16 StoryboardView", () => {
  it("shows the beats with their shots, lengths and locks", () => {
    render(<View />);
    expect(screen.getByText("7 beats · 43 shots · drag shots between beats, lock what you love")).toBeInTheDocument();
    expect(within(beat("Arrival")).getByText("0:27")).toBeInTheDocument();
    expect(within(beat("Wildlife")).getByText("Locked")).toBeInTheDocument();
    expect(within(beat("Arrival")).queryByText("Locked")).toBeNull();
    expect(chip("Wildlife", 0)).toHaveAccessibleName("hero, 0:04, locked");
    expect(chip("Arrival", 6)).toHaveAccessibleName("detail"); // not in the edit: no length
    expect(screen.queryByText("Save version")).toBeNull();
  });

  it("unsaved changes offer Save version; ⌘Z and ⇧⌘Z undo and redo", () => {
    const onSave = vi.fn();
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    render(<View d={{ dirty: true, can_undo: true, can_redo: true }} onSave={onSave} onUndo={onUndo} onRedo={onRedo} />);
    expect(screen.getByText("Unsaved changes ·")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save version" }));
    expect(onSave).toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "z", metaKey: true });
    fireEvent.keyDown(window, { key: "z", metaKey: true, shiftKey: true });
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onRedo).toHaveBeenCalledTimes(1);
  });

  it("nothing to undo: ⌘Z does nothing", () => {
    const onUndo = vi.fn();
    render(<View onUndo={onUndo} />);
    fireEvent.keyDown(window, { key: "z", metaKey: true });
    expect(onUndo).not.toHaveBeenCalled();
  });

  it("L locks the focused shot, Delete removes it, Space plays the hovered one", () => {
    const ops: DraftOp[] = [];
    render(<View onOp={(op) => ops.push(op)} />);
    fireEvent.focus(chip("Arrival", 1));
    fireEvent.keyDown(window, { key: "l" });
    fireEvent.keyDown(window, { key: "Delete" });
    expect(ops).toEqual([
      { kind: "lock_shot", ref: "b1#1", locked: true },
      { kind: "remove_shot", ref: "b1#1" },
    ]);
    fireEvent.focus(chip("Wildlife", 0));
    fireEvent.keyDown(window, { key: "Delete" }); // locked: never removed
    fireEvent.keyDown(window, { key: "l" });
    expect(ops.at(-1)).toEqual({ kind: "lock_shot", ref: "b4#0", locked: false });
    fireEvent.mouseEnter(chip("The coast", 0));
    fireEvent.keyDown(window, { key: " " });
    expect(screen.getByText("playing")).toBeInTheDocument();
  });

  it("a shot's popover tells why, and replaces, locks or removes it", () => {
    const ops: DraftOp[] = [];
    const opened: (string | null)[] = [];
    render(<View onOp={(op) => ops.push(op)} onOpenShot={(r) => opened.push(r)} />);
    fireEvent.click(chip("Waterfalls", 2));
    expect(opened).toEqual(["b3#2"]);
    const pop = screen.getByRole("dialog");
    expect(within(pop).getByText(/^Role: detail · 0:04 · Day/)).toBeInTheDocument();
    expect(within(pop).getByText("Softer focus on the face")).toBeInTheDocument();
    fireEvent.click(within(pop).getByRole("button", { name: "Use DSC_1046.MOV" }));
    expect(ops).toEqual([{ kind: "replace_shot", ref: "b3#2", segment_id: "seg_002001" }]);
    fireEvent.click(chip("Waterfalls", 0));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Lock shot" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" }));
    expect(ops.slice(1)).toEqual([
      { kind: "lock_shot", ref: "b3#0", locked: true },
      { kind: "remove_shot", ref: "b3#0" },
    ]);
  });

  it("a locked shot can't be replaced or removed from its popover", () => {
    render(<View defaultOpen="b4#0" />);
    const pop = screen.getByRole("dialog");
    expect(within(pop).queryByText("Replace with…")).toBeNull();
    expect(within(pop).getByRole("button", { name: "Remove" })).toBeDisabled();
    expect(within(pop).getByRole("button", { name: "Unlock shot" })).toBeInTheDocument();
  });

  it("drags a shot into another beat, and a beat to a new place", () => {
    const ops: DraftOp[] = [];
    render(<View onOp={(op) => ops.push(op)} />);
    const data = { setData: noop, setDragImage: noop, effectAllowed: "" };
    fireEvent.dragStart(chip("Arrival", 0), { dataTransfer: data });
    const target = chip("Waterfalls", 1);
    target.getBoundingClientRect = () => ({ left: 0, width: 92, top: 0, height: 52, right: 92, bottom: 52, x: 0, y: 0, toJSON: noop });
    dragAt(target, "dragover", 10);
    dragAt(target, "drop", 10);
    expect(ops).toEqual([{ kind: "move_shot", ref: "b1#0", beat_id: "b3", index: 1 }]);
    fireEvent.dragStart(within(beat("Finale")).getByRole("button", { name: "Drag Finale" }), { dataTransfer: data });
    const card = beat("Arrival");
    card.getBoundingClientRect = () => ({ left: 0, width: 400, top: 0, height: 300, right: 400, bottom: 300, x: 0, y: 0, toJSON: noop });
    dragAt(card, "dragover", 20);
    dragAt(card, "drop", 20);
    expect(ops[1]).toEqual({ kind: "move_beat", beat_id: "b7", index: 0 });
    // Dropped on a chip of another beat: the card under it takes the beat.
    fireEvent.dragStart(within(beat("Arrival")).getByRole("button", { name: "Drag Arrival" }), { dataTransfer: data });
    const coast = beat("The coast");
    coast.getBoundingClientRect = () => ({ left: 0, width: 400, top: 0, height: 300, right: 400, bottom: 300, x: 0, y: 0, toJSON: noop });
    dragAt(chip("The coast", 1), "dragover", 300);
    dragAt(chip("The coast", 1), "drop", 300);
    expect(ops[2]).toEqual({ kind: "move_beat", beat_id: "b1", index: 5 });
  });

  it("the ⋯ menu paces slower, locks every shot and moves the beat", async () => {
    const ops: DraftOp[] = [];
    render(<View onOp={(op) => ops.push(op)} />);
    const menu = async (item: string) => {
      const trigger = within(beat("Finale")).getByRole("button", { name: "More beat actions" });
      fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
      fireEvent.click(await screen.findByRole("menuitem", { name: item }));
    };
    await menu("Slower");
    await menu("Lock every shot");
    await menu("Move earlier");
    expect(ops).toEqual([
      { kind: "pace_beat", beat_id: "b7", faster: false },
      { kind: "lock_shot", ref: "b7#0", locked: true },
      { kind: "lock_shot", ref: "b7#1", locked: true },
      { kind: "lock_shot", ref: "b7#2", locked: true },
      { kind: "move_beat", beat_id: "b7", index: 5 },
    ]);
  });

  it("a regenerating beat shimmers and can't be changed; the others stay usable", () => {
    const onRegenerateBeat = vi.fn();
    render(<View d={{ regenerating: ["b5"] }} onRegenerateBeat={onRegenerateBeat} />);
    const busy = beat("Up in the canopy");
    expect(within(busy).getByText("Regenerating this beat…")).toBeInTheDocument();
    expect(within(busy).getByRole("button", { name: "Regenerate" })).toBeDisabled();
    fireEvent.click(within(beat("Arrival")).getByRole("button", { name: "Regenerate" }));
    expect(onRegenerateBeat).toHaveBeenCalledWith("b1");
  });

  it("warns when the locks can't fit, and shows a beat's own notice", () => {
    render(<View d={{ metrics: { locks: { over_frames: 900, frames: 9000, shots: 30 } } }} warnings={{ b2: "Into the jungle is already as fast as it gets" }} />);
    expect(screen.getByText(/Your locked shots run 0:30 past the longest this edit can be/)).toBeInTheDocument();
    expect(within(beat("Into the jungle")).getByText("Into the jungle is already as fast as it gets")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ screen

const posts: { path: string; body?: unknown; params?: unknown }[] = [];
let draft: DraftState = DRAFT;
let refuse: { status: number; detail: string } | null = null;
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => {
      if (path === "/api/edits/{eid}/draft") return Promise.resolve({ data: draft, response: { status: 200 } });
      if (path === "/api/edits/{eid}/shots/{shot}/alternatives") return Promise.resolve({ data: { items: ALTERNATIVES, locked: false } });
      return Promise.resolve({ error: { detail: "unknown" }, response: { status: 404 } });
    },
    POST: (path: string, o: { body?: unknown; params?: unknown }) => {
      posts.push({ path, body: o?.body, params: o?.params });
      if (refuse) return Promise.resolve({ error: { detail: refuse.detail }, response: { status: refuse.status } });
      if (path === "/api/edits/{eid}/draft/ops" || path === "/api/edits/{eid}/draft/undo") {
        draft = { ...draft, dirty: true, can_undo: path.endsWith("ops") };
        return Promise.resolve({ data: { ...draft, regenerating: undefined }, response: { status: 200 } });
      }
      if (path === "/api/edits/{eid}/versions") {
        draft = { ...draft, dirty: false, base_version: 3 };
        return Promise.resolve({ data: { version: 3 }, response: { status: 201 } });
      }
      if (path === "/api/edits/{eid}/beats/{bid}/regenerate") {
        draft = { ...draft, regenerating: ["b2"] };
        return Promise.resolve({ data: { job_id: 5 }, response: { status: 202 } });
      }
      return Promise.resolve({ data: {}, response: { status: 200 } });
    },
  },
}));

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

function mount(start: DraftState = DRAFT) {
  posts.length = 0;
  refuse = null;
  draft = start;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/edits/E1/storyboard"]}>
        <Routes>
          <Route path="/p/:pid/edits/:eid/storyboard" element={<StoryboardScreen />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("StoryboardScreen sends ops in order, then saves before Preview", async () => {
  mount();
  fireEvent.click(await within(await screen.findByRole("region", { name: "Arrival" })).findByRole("button", { name: "Faster" }));
  fireEvent.click(within(screen.getByRole("region", { name: "Waterfalls" })).getByRole("button", { name: "Faster" }));
  expect(await screen.findByText("Unsaved changes ·")).toBeInTheDocument();
  await waitFor(() => expect(posts.filter((p) => p.path === "/api/edits/{eid}/draft/ops")).toHaveLength(2));
  expect(posts.map((p) => (p.body as { op: DraftOp }).op)).toEqual([
    { kind: "pace_beat", beat_id: "b1", faster: true },
    { kind: "pace_beat", beat_id: "b3", faster: true },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Preview" }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/p/P1/edits/E1"));
  expect(posts.at(-1)!.path).toBe("/api/edits/{eid}/versions");
});

it("StoryboardScreen shows a refused pace on its beat, and follows a beat regenerating", async () => {
  mount();
  refuse = { status: 422, detail: "Arrival is already as fast as it gets" };
  fireEvent.click(await within(await screen.findByRole("region", { name: "Arrival" })).findByRole("button", { name: "Faster" }));
  expect(await within(screen.getByRole("region", { name: "Arrival" })).findByText("Arrival is already as fast as it gets")).toBeInTheDocument();
  refuse = null;
  await act(async () => {
    fireEvent.click(within(screen.getByRole("region", { name: "Into the jungle" })).getByRole("button", { name: "Regenerate" }));
  });
  expect(await within(screen.getByRole("region", { name: "Into the jungle" })).findByText("Regenerating this beat…")).toBeInTheDocument();
  expect(posts.at(-1)!.params).toEqual({ path: { eid: "E1", bid: "b2" } });
});

it("StoryboardScreen undoes and redoes on the server, and shows a refusal with no beat", async () => {
  mount({ ...DRAFT, can_undo: true, can_redo: true });
  await screen.findByRole("region", { name: "Arrival" });
  await act(async () => {
    fireEvent.keyDown(window, { key: "z", metaKey: true });
  });
  await waitFor(() => expect(posts.map((p) => p.path)).toContain("/api/edits/{eid}/draft/undo"));
  refuse = { status: 409, detail: "This shot is locked: unlock it to remove it" };
  fireEvent.click(screen.getByRole("button", { name: "Redo" }));
  await waitFor(() => expect(posts.map((p) => p.path)).toContain("/api/edits/{eid}/draft/redo"));
  await waitFor(() => expect(useToasts.getState().items.map((x) => x.message)).toContain("This shot is locked: unlock it to remove it"));
});
