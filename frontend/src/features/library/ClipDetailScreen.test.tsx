import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { ClipDetailScreen } from "./ClipDetailScreen";
import { DETAIL } from "./fixtures";

type Opts = { body?: unknown; params?: { path?: Record<string, unknown> } };
const calls: { method: string; path: string; opts?: Opts }[] = [];
const reply = (method: string, path: string, opts?: Opts) => {
  calls.push({ method, path, opts });
  if (path === "/api/projects/{pid}/clips/{aid}") return Promise.resolve({ data: { ...DETAIL, asset_id: opts?.params?.path?.aid } });
  if (path.startsWith("/api/media")) return Promise.resolve({ data: { frames: [], silent: true, peaks: "" } });
  if (method === "PATCH") return Promise.resolve({ data: {} });
  return Promise.resolve({ error: { detail: "unmocked" } });
};
vi.mock("@/api/client", () => ({
  api: {
    GET: (p: string, o?: Opts) => reply("GET", p, o),
    PATCH: (p: string, o?: Opts) => reply("PATCH", p, o),
    POST: (p: string, o?: Opts) => reply("POST", p, o),
  },
}));

it("decision keys, L inside the player, and ] for the next clip", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/p/P1/clips/1"]}>
        <Routes>
          <Route path="/p/:pid/clips/:aid" element={<ClipDetailScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const player = await screen.findByLabelText("Player");
  fireEvent.keyDown(player, { key: "u" });
  await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.opts?.body)).toEqual([{ disposition: "USE" }]));
  fireEvent.keyDown(player, { key: "l" }); // the player's: play
  fireEvent.keyDown(document.body, { key: "x" });
  await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.opts?.body)).toEqual([{ disposition: "USE" }, { include: "never" }]));
  fireEvent.keyDown(document.body, { key: "l" }); // outside the player: always include
  await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").at(-1)?.opts?.body).toEqual({ include: "always" }));
  fireEvent.keyDown(document.body, { key: "]" });
  await waitFor(() => expect(calls.some((c) => c.method === "GET" && c.opts?.params?.path?.aid === 2)).toBe(true));
});
