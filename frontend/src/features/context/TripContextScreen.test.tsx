import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { TripContextScreen } from "./TripContextScreen";

const calls: { method: string; path: string; body?: unknown }[] = [];
const replies: Record<string, unknown> = {};
const reply = (method: string, path: string, opts?: { body?: unknown }) => {
  calls.push({ method, path, body: opts?.body });
  return Promise.resolve({ data: replies[`${method} ${path}`], error: replies[`${method} ${path}`] ? undefined : { detail: "unmocked" } });
};
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string, o?: { body?: unknown }) => reply("GET", path, o),
    POST: (path: string, o?: { body?: unknown }) => reply("POST", path, o),
    PUT: (path: string, o?: { body?: unknown }) => reply("PUT", path, o),
  },
}));

it("parses pasted notes as a job, merges the proposal without replacing typed values, then saves", async () => {
  replies["GET /api/projects/{pid}/trip-context"] = {
    revision: 1,
    trip_name: "CR",
    days: [{ date: "2026-07-14", place: "San José", notes: "" }],
    people: [],
    must_include: [],
    avoid: [],
    free_notes: "",
  };
  replies["GET /api/projects/{pid}/inventory"] = { days: [{ date: "2026-07-14" }, { date: "2026-07-15" }] };
  replies["POST /api/projects/{pid}/trip-context/parse"] = { job_id: 7 };
  replies["GET /api/jobs/{job_id}"] = {
    state: "done",
    error: null,
    result: { proposal: { trip_name: "Costa Rica 2026", days: [{ date: "2026-07-15", place: "Arenal", notes: "" }], people: [], must_include: [], avoid: ["car interiors"], free_notes: "" } },
  };
  replies["PUT /api/projects/{pid}/trip-context"] = { revision: 2, summaries_job: 9 };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/context"]}>
        <Routes>
          <Route path="/p/:pid/context" element={<TripContextScreen />} />
          <Route path="/p/:pid/analyze" element={<p>analysis setup</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole("tab", { name: "Quick paste" }));
  fireEvent.change(screen.getByLabelText("Trip notes"), { target: { value: "Day 2 Arenal. Avoid car interiors." } });
  fireEvent.click(screen.getByRole("button", { name: "Parse" }));
  expect(await screen.findByDisplayValue("Arenal", undefined, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByDisplayValue("CR")).toBeInTheDocument(); // typed name kept
  expect(screen.getByText("car interiors")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("analysis setup")).toBeInTheDocument();
  const put = calls.find((c) => c.method === "PUT")!.body as { days: { date: string }[]; avoid: string[] };
  expect(put.days.map((d) => d.date)).toEqual(["2026-07-14", "2026-07-15"]);
  expect(put.avoid).toEqual(["car interiors"]);
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/jobs/{job_id}").length).toBe(1));
});
