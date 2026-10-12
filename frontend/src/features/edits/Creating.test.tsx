import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { CreatingScreen } from "./CreatingScreen";
import { CreatingView, type CreatingViewProps } from "./CreatingView";
import { beatInProgress, creatingStages, type Creating, type CreatingJob } from "./creating";
import { CARDS } from "./fixtures";

const noop = () => {};
const BEATS: Creating["beats"] = [
  { beat_id: "b1", title: "Arrival", intent: "Land and look around", sample_ids: [1, 2, 3] },
  { beat_id: "b2", title: "Wildlife", intent: "Toucan and sloth", sample_ids: [] },
  { beat_id: "b3", title: "Finale", intent: "Sunset", sample_ids: [] },
];
const job = (state: CreatingJob["state"], creating: Creating, error: string | null = null): CreatingJob => ({ job_id: 7, state, error, result: { creating } });

describe("S15 model", () => {
  it("steps follow the generation, then the preview", () => {
    const states = (s: Parameters<typeof creatingStages>[0]) => creatingStages(s).map((x) => x.state);
    expect(states({ generation: job("running", {}), preview: undefined, seconds: 300 })[0]).toBe("running");
    const planning = creatingStages({ generation: job("running", { step: "planning", moments: 412, candidates: 186 }), preview: undefined, seconds: 300 });
    expect(planning.map((x) => x.state)).toEqual(["done", "running", "pending", "pending", "pending", "pending", "pending"]);
    expect(planning[0]!.note).toBe("412 clips → 186 candidates");
    expect(planning[3]!.label).toBe("Fitting to 5:00");
    const fitting = states({ generation: job("running", { step: "fitting", beats: BEATS }), preview: undefined, seconds: 300 });
    expect(fitting).toEqual(["done", "done", "done", "running", "running", "pending", "pending"]);
    const made = states({ generation: job("done", { step: "checking" }), preview: { state: "running" }, seconds: 300 });
    expect(made).toEqual(["done", "done", "done", "done", "done", "done", "running"]);
    expect(states({ generation: job("done", { step: "checking" }), preview: { state: "done" }, seconds: 300 }).at(-1)).toBe("done");
    expect(states({ generation: job("failed", { step: "selecting" }), preview: undefined, seconds: 300 })[2]).toBe("failed");
  });

  it("a failed or paused preview and a paused generation show as such", () => {
    const at = (s: Parameters<typeof creatingStages>[0]) => creatingStages(s).map((x) => x.state);
    expect(at({ generation: job("done", { step: "checking" }), preview: { state: "failed" }, seconds: 60 }).at(-1)).toBe("failed");
    expect(at({ generation: job("done", { step: "checking" }), preview: { state: "paused" }, seconds: 60 }).at(-1)).toBe("paused");
    expect(at({ generation: job("paused", { step: "planning" }), preview: undefined, seconds: 60 })[1]).toBe("paused");
  });

  it("the beat being worked on is the first without frames while shots are chosen", () => {
    expect(beatInProgress({ step: "selecting", beats: BEATS })).toBe(1);
    expect(beatInProgress({ step: "fitting", beats: BEATS })).toBeNull();
  });
});

function View(p: Partial<CreatingViewProps>) {
  const props: CreatingViewProps = {
    title: "Costa Rica — 5 min cinematic",
    seconds: 300,
    generation: job("running", { step: "selecting", moments: 412, candidates: 186, beats: BEATS }),
    preview: undefined,
    frame: (sid) => `/f/${sid}`,
    onBackground: noop,
    onCancel: noop,
    onRetry: noop,
    onView: noop,
    ...p,
  };
  return <CreatingView {...props} />;
}

describe("CreatingView", () => {
  it("running: steps, beats with frames, the one in progress highlighted, background and cancel", () => {
    const bg = vi.fn();
    const cancel = vi.fn();
    render(<View onBackground={bg} onCancel={cancel} />);
    expect(screen.getByRole("heading", { name: "Creating your edit" })).toBeInTheDocument();
    expect(screen.getByText("412 clips → 186 candidates")).toBeInTheDocument();
    expect(screen.getByText("Beat 2 of 3 · Wildlife")).toBeInTheDocument();
    const story = within(screen.getByRole("region", { name: "Story taking shape" }));
    expect(story.getByText("Arrival")).toBeInTheDocument();
    expect(story.getByText("Wildlife").closest("[aria-current]")).toHaveAttribute("aria-current", "step");
    fireEvent.click(screen.getByRole("button", { name: "Run in background" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(bg).toHaveBeenCalled();
    expect(cancel).toHaveBeenCalled();
  });

  it("failed: the reason in plain words and Try again; cancelled: Start again", () => {
    const retry = vi.fn();
    const { rerender } = render(<View generation={job("failed", { step: "planning" }, "PermanentError: only one usable clip: an edit needs at least two")} onRetry={retry} />);
    expect(screen.getByRole("heading", { name: "The edit couldn't be made" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("only one usable clip: an edit needs at least two");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Run in background" })).not.toBeInTheDocument();
    rerender(<View generation={job("cancelled", { step: "planning" })} onRetry={retry} />);
    expect(screen.getByRole("heading", { name: "Edit cancelled" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(retry).toHaveBeenCalledTimes(2);
  });

  it("made: View storyboard", () => {
    const view = vi.fn();
    render(<View generation={job("done", { step: "checking", beats: BEATS })} preview={{ state: "done" }} onView={view} />);
    expect(screen.getByRole("heading", { name: "Your edit is ready" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View storyboard" }));
    expect(view).toHaveBeenCalled();
  });
});

// ------------------------------------------------------------------ screen

const posts: { path: string; body?: unknown; params?: unknown }[] = [];
let generation: CreatingJob = job("running", { step: "planning" });
let renders: unknown[] = [];
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => {
      if (path === "/api/projects/{pid}/edits") return Promise.resolve({ data: { items: CARDS } });
      if (path === "/api/jobs/{job_id}") return Promise.resolve({ data: generation });
      if (path === "/api/edits/{eid}") return Promise.resolve({ data: { version: 3, renders } });
      return Promise.resolve({ error: { detail: "unknown" } });
    },
    POST: (path: string, o: { body?: unknown; params?: unknown }) => {
      posts.push({ path, body: o?.body, params: o?.params });
      if (path === "/api/renders") {
        renders = [{ render_id: 1, kind: "preview", status: "rendering", version: 3 }];
        return Promise.resolve({ data: { job_id: 9, render_id: 1 } });
      }
      if (path === "/api/edits/{eid}/generate") return Promise.resolve({ data: { job_id: 8 } });
      return Promise.resolve({ data: {} });
    },
  },
}));

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

const EID = CARDS[0]!.edit_id;

function mount(state: CreatingJob, existing: unknown[] = []) {
  posts.length = 0;
  generation = state;
  renders = existing;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/p/P1/edits/${EID}/creating?job=7`]}>
        <Routes>
          <Route path="/p/:pid/edits/:eid/creating" element={<><CreatingScreen /><Where /></>} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("CreatingScreen renders the version's preview once made, then opens the edit", async () => {
  mount(job("done", { step: "checking", beats: BEATS }));
  await waitFor(() => expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1));
  expect(posts.find((p) => p.path === "/api/renders")!.body).toEqual({ edit_id: EID, version: 3, final: false, codec: "h264" });
  fireEvent.click(await screen.findByRole("button", { name: "View storyboard" }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/p/P1/edits/${EID}`));
  expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1); // one preview
});

it("CreatingScreen follows a preview the version already has, and starts none", async () => {
  mount(job("done", { step: "checking", beats: BEATS }), [{ render_id: 4, kind: "preview", status: "done", version: 3 }]);
  expect(await screen.findByRole("heading", { name: "Your edit is ready" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getAllByRole("img", { name: "Done" })).toHaveLength(7)); // the preview too
  expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(0);
});

it("CreatingScreen cancels the job, retries with a new one, and runs in the background", async () => {
  mount(job("running", { step: "selecting", beats: BEATS }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(posts.some((p) => p.path === "/api/jobs/{job_id}/{action}")).toBe(true));
  expect(posts.find((p) => p.path === "/api/jobs/{job_id}/{action}")!.params).toEqual({ path: { job_id: 7, action: "cancel" } });
  fireEvent.click(screen.getByRole("button", { name: "Run in background" }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/p/P1/edits"));
});

it("CreatingScreen's Try again starts a new generation and follows it", async () => {
  mount(job("failed", { step: "planning" }, "PermanentError: no candidates"));
  fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/p/P1/edits/${EID}/creating?job=8`));
  expect(posts.some((p) => p.path === "/api/edits/{eid}/generate")).toBe(true);
});

it("CreatingScreen makes the preview again when its file was deleted", async () => {
  mount(job("done", { step: "checking", beats: BEATS }), [{ render_id: 4, kind: "preview", status: "missing", version: 3 }]);
  await waitFor(() => expect(posts.filter((p) => p.path === "/api/renders")).toHaveLength(1));
});
