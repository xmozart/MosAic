import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { useToasts } from "@/lib/toasts";

import { HomeScreen } from "./HomeScreen";

type Reply = { data?: unknown; error?: unknown };
const calls: string[] = [];
const replies: Record<string, Reply> = {};
const reply = (method: string, path: string): Promise<Reply> => {
  calls.push(`${method} ${path}`);
  return Promise.resolve(replies[`${method} ${path}`] ?? { data: undefined, error: { detail: "unmocked" } });
};

vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => reply("GET", path),
    POST: (path: string) => reply("POST", path),
    DELETE: (path: string) => reply("DELETE", path),
  },
}));

function renderHome() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<HomeScreen />} />
          <Route path="/p/:pid" element={<p>project page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls.length = 0;
  for (const k of Object.keys(replies)) delete replies[k];
  replies["GET /api/auth/status"] = { data: { mode: "desktop" } };
  replies["GET /api/projects"] = { data: { items: [] } };
  useToasts.setState({ items: [] });
});

describe("HomeScreen", () => {
  it("in the Mac app, Open footage folder uses the native picker (ADR 0060)", async () => {
    const open = vi.fn().mockResolvedValue("/Users/me/Trips/Iceland");
    window.__TAURI__ = { dialog: { open } };
    replies["POST /api/projects/preview"] = {
      data: { name: "Iceland", placement: "in_folder", counts: { videos: 3, photos: 0, folders: 0, complete: true }, project_id: "P1" },
    };
    replies["POST /api/projects"] = { data: { id: "P1", created: false } };
    try {
      renderHome();
      fireEvent.click(await screen.findByRole("button", { name: /Open footage folder/ }));
      expect(await screen.findByText("project page")).toBeInTheDocument();
      expect(open).toHaveBeenCalledWith(expect.objectContaining({ directory: true, multiple: false }));
      expect(screen.queryByLabelText("Folder")).toBeNull(); // no typed-path dialog
    } finally {
      delete window.__TAURI__;
    }
  });

  it("shows the empty state, and a folder that is already a project opens without confirmation", async () => {
    replies["POST /api/projects/preview"] = {
      data: { name: "Trip", placement: "in_folder", counts: { videos: 3, photos: 0, folders: 0, complete: true }, project_id: "P1" },
    };
    replies["POST /api/projects"] = { data: { id: "P1", created: false } };
    renderHome();
    expect(await screen.findByText("Pick a folder of trip footage")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Open footage folder/ }));
    fireEvent.change(await screen.findByLabelText("Folder"), { target: { value: "/Movies/Trip" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("project page")).toBeInTheDocument();
    expect(calls).toContain("POST /api/projects");
    expect(screen.queryByText("Create project")).toBeNull();
  });

  it("a failed open of an existing project is reported, not swallowed", async () => {
    replies["POST /api/projects/preview"] = {
      data: { name: "Trip", placement: "in_folder", counts: { videos: 3, photos: 0, folders: 0, complete: true }, project_id: "P1" },
    };
    replies["POST /api/projects"] = { error: { detail: "The project's database is newer than this app." } };
    renderHome();
    fireEvent.click(await screen.findByRole("button", { name: /Open footage folder/ }));
    fireEvent.change(await screen.findByLabelText("Folder"), { target: { value: "/Movies/Trip" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(useToasts.getState().items.map((t) => t.message)).toContain("The project's database is newer than this app."),
    );
  });

  it("a new folder goes through the confirm dialog", async () => {
    replies["POST /api/projects/preview"] = {
      data: { name: "Trip", placement: "split", counts: { videos: 3, photos: 1, folders: 0, complete: true }, project_id: null },
    };
    renderHome();
    fireEvent.click(await screen.findByRole("button", { name: /Open footage folder/ }));
    fireEvent.change(await screen.findByLabelText("Folder"), { target: { value: "/Movies/Trip" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Found 3 videos and 1 photo in 1 folder")).toBeInTheDocument();
    expect(calls).not.toContain("POST /api/projects");
  });
});
