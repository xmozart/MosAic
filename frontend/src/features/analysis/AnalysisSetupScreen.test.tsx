import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { AnalysisSetupScreen } from "./AnalysisSetupScreen";
import { ESTIMATES, SETTINGS } from "./fixtures";

const calls: { method: string; path: string; opts?: { body?: unknown; params?: { query?: Record<string, unknown> } } }[] = [];
const reply = (method: string, path: string, opts?: (typeof calls)[number]["opts"]) => {
  calls.push({ method, path, opts });
  const q = opts?.params?.query ?? {};
  const data: Record<string, unknown> = {
    "GET /api/projects/{pid}/settings": { settings: SETTINGS },
    "GET /api/projects/{pid}/analysis/estimate": ESTIMATES[(q.mode as keyof typeof ESTIMATES) ?? "balanced"],
    "GET /api/providers": { vision: { provider: "fake", model: "fake" }, planner: { provider: "fake", model: "fake" } },
    "GET /api/settings": { "ai.local_only": { value: false } },
    "GET /api/system/info": { hardware: { cpu_model: "Apple M4" } },
    "PATCH /api/projects/{pid}/settings": { settings: SETTINGS },
    "POST /api/projects/{pid}/analysis-runs": { job_id: 42 },
  };
  const d = data[`${method} ${path}`];
  return Promise.resolve(d === undefined ? { error: { detail: "unmocked" } } : { data: d });
};
vi.mock("@/api/client", () => ({
  api: {
    GET: (p: string, o?: never) => reply("GET", p, o),
    POST: (p: string, o?: never) => reply("POST", p, o),
    PATCH: (p: string, o?: never) => reply("PATCH", p, o),
  },
}));

it("saves Advanced edits as project settings, starts the chosen mode and opens S9", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/analyze"]}>
        <Routes>
          <Route path="/p/:pid/analyze" element={<AnalysisSetupScreen />} />
          <Route path="/p/:pid/analysis" element={<p>progress</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole("radio", { name: /Thorough/ }));
  fireEvent.click(screen.getByRole("button", { name: /Advanced/ }));
  fireEvent.click(await screen.findByRole("radio", { name: "High" }));
  expect(await screen.findByText("Changed here")).toBeInTheDocument();
  // Estimates follow unsaved edits, once typing pauses.
  await waitFor(() => expect(calls.some((c) => c.path.endsWith("/estimate") && c.opts?.params?.query?.overrides)).toBe(true));
  fireEvent.click(await screen.findByRole("button", { name: "Analyze" }));
  expect(await screen.findByText("progress")).toBeInTheDocument();
  const patch = calls.find((c) => c.method === "PATCH")!;
  expect(patch.opts?.body).toEqual({ values: { "analysis.forced_max_shot": "30", "analysis.mode": "thorough" } });
  const run = calls.find((c) => c.method === "POST")!;
  expect(run.opts?.body).toEqual({ mode: "thorough" });
  expect(calls.indexOf(patch)).toBeLessThan(calls.indexOf(run));
});
