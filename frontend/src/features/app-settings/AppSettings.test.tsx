import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";

import { useToasts } from "@/lib/toasts";

import { AppSettingsScreen } from "./AppSettingsScreen";
import { AppSettingsView, type AppSettingsViewProps } from "./AppSettingsView";
import { NO_KEY, OPTIONS, PROVIDERS, ROOTS, SETTINGS, SYSTEM } from "./fixtures";
import { keyProviders } from "./model";

const noop = () => {};
const base: AppSettingsViewProps = {
  theme: "system",
  onTheme: noop,
  settings: SETTINGS,
  onSetting: noop,
  providers: PROVIDERS,
  options: OPTIONS,
  onProvider: noop,
  keyChecks: {},
  onSaveKey: async () => {},
  onValidateKey: noop,
  onRemoveKey: noop,
  system: SYSTEM,
};

function cleanupAndRender(ui: ReactElement) {
  cleanup();
  return render(ui);
}

const rows = () => within(screen.getByRole("table", { name: "Models by task" })).getAllByRole("row").slice(1); // after the header

describe("AppSettingsView", () => {
  it("one key card per cloud provider in use; models by task show source and mode", () => {
    expect(keyProviders(PROVIDERS).map((k) => k.provider)).toEqual(["anthropic"]);
    render(<AppSettingsView {...base} />);
    expect(screen.getByText("Anthropic API key")).toBeInTheDocument();
    expect(screen.getByText("Stored in the system keychain")).toBeInTheDocument();
    expect(screen.getByText("••••7F3A")).toBeInTheDocument();
    expect(rows()).toHaveLength(8);
    const speech = within(rows().find((r) => r.textContent?.includes("Speech"))!);
    expect(speech.getByText("From: your preference")).toBeInTheDocument();
    expect(speech.getByText("On this computer")).toBeInTheDocument();
    expect(speech.getByRole("combobox", { name: "Speech: model" })).toHaveValue("medium");
    expect(speech.getByRole("combobox", { name: "Speech: provider" })).toBeDisabled(); // only one provider can serve it
    const scenes = within(rows()[0]!);
    expect(scenes.getByText("Understanding scenes")).toBeInTheDocument();
    expect(scenes.getByText("From: default")).toBeInTheDocument();
    expect(scenes.getByText("Cloud")).toBeInTheDocument();
    expect(scenes.queryByRole("button", { name: /Reset/ })).toBeNull();
  });

  it("changing a task's provider uses its preset model; a model change and Reset call back", () => {
    const change = vi.fn();
    render(<AppSettingsView {...base} onProvider={change} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Story planning: provider" }), { target: { value: "codex-cli" } });
    expect(change).toHaveBeenLastCalledWith("planner", { provider: "codex-cli", model: "gpt-5.5" });
    const model = screen.getByRole("combobox", { name: "Understanding scenes: model" });
    fireEvent.change(model, { target: { value: "claude-opus-5-5" } });
    fireEvent.blur(model);
    expect(change).toHaveBeenLastCalledWith("vision", { provider: "anthropic", model: "claude-opus-5-5" });
    fireEvent.change(screen.getByRole("combobox", { name: "Speech: model" }), { target: { value: "large-v3" } });
    expect(change).toHaveBeenLastCalledWith("transcriber", { provider: "faster-whisper", model: "large-v3" });
    fireEvent.click(screen.getByRole("button", { name: "Reset Speech" }));
    expect(change).toHaveBeenLastCalledWith("transcriber", null);
  });

  it("key missing and key invalid", () => {
    const save = vi.fn(async () => {});
    const first = render(<AppSettingsView {...base} providers={NO_KEY} onSaveKey={save} />);
    expect(screen.getByText(/Without a key, the tasks below that use Anthropic can't run/)).toBeInTheDocument();
    const field = screen.getByLabelText("Anthropic API key");
    fireEvent.change(field, { target: { value: "sk-ant-test-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(save).toHaveBeenCalledWith("anthropic", "sk-ant-test-key");
    expect(field).toHaveValue(""); // write-only: cleared on save
    first.unmount();
    render(<AppSettingsView {...base} keyChecks={{ anthropic: "invalid" }} />);
    expect(screen.getByText("Key was rejected")).toBeInTheDocument();
  });

  it("a key the user entered can be removed; a deployment key can't", () => {
    const remove = vi.fn();
    const first = render(<AppSettingsView {...base} onRemoveKey={remove} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove key" }));
    expect(remove).toHaveBeenCalledWith("anthropic");
    first.unmount();
    const deployed = Object.fromEntries(
      Object.entries(PROVIDERS).map(([k, v]) => [k, v.key ? { ...v, key: { configured: true, last4: "WXYZ", store: "docker" as const, from_deployment: true } } : v]),
    );
    render(<AppSettingsView {...base} providers={deployed} />);
    expect(screen.queryByRole("button", { name: "Remove key" })).toBeNull();
    expect(screen.getByText(/Provided as a Docker secret · a key you add here is used instead/)).toBeInTheDocument();
  });

  it("local only pauses cloud tasks and says what leaves this computer", () => {
    const set = vi.fn();
    const { rerender } = render(<AppSettingsView {...base} onSetting={set} />);
    const leaves = within(screen.getByText("What leaves this computer in Hybrid").closest("div")!);
    expect(leaves.getAllByLabelText("Sent")).toHaveLength(2);
    expect(leaves.getAllByLabelText("Never sent")).toHaveLength(3);
    fireEvent.click(screen.getByRole("radio", { name: /Local only/ }));
    expect(set).toHaveBeenLastCalledWith("ai.local_only", true);
    rerender(<AppSettingsView {...base} settings={{ ...SETTINGS, "ai.local_only": { value: true, source: "user" } }} />);
    expect(screen.getByText(/Local only is on: cloud and installed-app tasks are paused/)).toBeInTheDocument();
    expect(screen.getByText("Local only is on: nothing is sent to check the key.")).toBeInTheDocument();
    expect(within(rows()[0]!).getByText("Paused · local only")).toBeInTheDocument();
    expect(within(rows()[0]!).getByRole("combobox", { name: "Understanding scenes: model" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled(); // nothing is sent
    expect(within(rows().find((r) => r.textContent?.includes("Speech"))!).getByText("On this computer")).toBeInTheDocument();
    expect(within(screen.getByText("What leaves this computer in Local only").closest("div")!).queryAllByLabelText("Sent")).toHaveLength(0);
  });

  it("theme, analysis defaults and workers", () => {
    const theme = vi.fn();
    const set = vi.fn();
    render(<AppSettingsView {...base} onTheme={theme} onSetting={set} />);
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(theme).toHaveBeenCalledWith("dark");
    fireEvent.click(screen.getByRole("radio", { name: "Thorough" }));
    expect(set).toHaveBeenLastCalledWith("analysis.mode", "thorough");
    const limit = screen.getByLabelText("Default AI cost limit in dollars");
    fireEvent.change(limit, { target: { value: "20" } });
    fireEvent.blur(limit);
    expect(set).toHaveBeenLastCalledWith("ai.budget.per_job_usd", 20);
    fireEvent.click(screen.getByRole("radio", { name: "4" }));
    expect(set).toHaveBeenLastCalledWith("workers.cpu", 4);
    cleanupAndRender(<AppSettingsView {...base} settings={{ ...SETTINGS, "workers.cpu": { value: 6, source: "user" } }} />);
    expect(screen.getByRole("radio", { name: "Custom: 6" })).toHaveAttribute("aria-checked", "true");
  });

  it("a provider the options don't offer still shows as the current one", () => {
    render(<AppSettingsView {...base} providers={{ ...PROVIDERS, vision: { ...PROVIDERS.vision!, provider: "fake", model: "fake-1", mode: "local" } }} />);
    const select = screen.getByRole("combobox", { name: "Understanding scenes: provider" });
    expect(select).toHaveValue("fake");
    expect(within(select).getByRole("option", { name: "fake" })).toBeDisabled();
    expect(screen.getByText(/Apple M3 Max · 16 threads · 64 GB memory/)).toBeInTheDocument();
  });

  it("media roots only on a server: add and remove, deployment roots stay", () => {
    const add = vi.fn();
    const remove = vi.fn();
    const { rerender } = render(<AppSettingsView {...base} />);
    expect(screen.queryByRole("region", { name: "Media roots" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Media roots" })).toBeNull();
    rerender(<AppSettingsView {...base} roots={ROOTS} onAddRoot={add} onRemoveRoot={remove} />);
    const region = within(screen.getByRole("region", { name: "Media roots" }));
    expect(region.queryByRole("button", { name: "Remove /media/travel" })).toBeNull();
    fireEvent.click(region.getByRole("button", { name: "Remove /mnt/nas/video" }));
    expect(remove.mock.calls[0]![0].id).toBe(2);
    fireEvent.change(region.getByLabelText("Folder on the server"), { target: { value: "/srv/trips" } });
    fireEvent.click(region.getByRole("button", { name: /Add media root/ }));
    expect(add).toHaveBeenCalledWith("/srv/trips", "");
  });
});

// ------------------------------------------------------------------ screen

const calls: { method: string; path: string; body?: unknown; params?: unknown }[] = [];
let validateFails = false;
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => {
      const data: Record<string, unknown> = {
        "/api/settings": SETTINGS,
        "/api/providers": PROVIDERS,
        "/api/providers/options": OPTIONS,
        "/api/system/info": SYSTEM,
        "/api/projects": { items: [{ id: "P1", name: "Costa Rica 2026" }] },
        "/api/auth/status": { mode: "desktop" },
      };
      return Promise.resolve(path in data ? { data: data[path] } : { error: { detail: "x" } });
    },
    PATCH: (path: string, o: { body: unknown }) => {
      calls.push({ method: "PATCH", path, body: o.body });
      return Promise.resolve({ data: {} });
    },
    PUT: (path: string, o: { body: unknown; params: unknown }) => {
      calls.push({ method: "PUT", path, body: o.body, params: o.params });
      return Promise.resolve({ data: { configured: true, last4: "WXYZ" } });
    },
    POST: (path: string, o: { params: unknown }) => {
      calls.push({ method: "POST", path, params: o.params });
      if (validateFails) return Promise.reject(new TypeError("Failed to fetch"));
      return Promise.resolve({ data: { ok: false, provider: "anthropic" } });
    },
    DELETE: (path: string, o: { params: unknown }) => {
      calls.push({ method: "DELETE", path, params: o.params });
      return Promise.resolve({ data: undefined });
    },
  },
}));

it("AppSettingsScreen saves settings and models, stores a key once and validates it", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/settings"]}>
        <Routes>
          <Route path="/settings" element={<AppSettingsScreen />} />
          <Route path="/p/:pid/settings" element={<p>project settings</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Anthropic API key")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: /Local only/ }));
  await waitFor(() => expect(calls).toContainEqual({ method: "PATCH", path: "/api/settings", body: { "ai.local_only": true } }));
  fireEvent.change(screen.getByRole("combobox", { name: "Story planning: provider" }), { target: { value: "claude-cli" } });
  await waitFor(() => expect(calls).toContainEqual({ method: "PATCH", path: "/api/providers", body: { planner: { provider: "claude-cli", model: "claude-sonnet-5-5" } } }));
  fireEvent.click(screen.getByRole("button", { name: "Replace key" }));
  fireEvent.change(screen.getByLabelText("Anthropic API key"), { target: { value: "sk-ant-new" } });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  await waitFor(() => expect(calls).toContainEqual({ method: "PUT", path: "/api/secrets/{ref}", body: { value: "sk-ant-new" }, params: { path: { ref: "ai/anthropic" } } }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/secrets/{ref}/validate")).toBe(true));
  expect(await screen.findByText("Key was rejected")).toBeInTheDocument();
  expect(JSON.stringify(localStorage)).not.toContain("sk-ant-new");
  expect(JSON.stringify(sessionStorage)).not.toContain("sk-ant-new");
  // Reset sends null; Remove key deletes it; a failed check is not a rejected key.
  fireEvent.click(screen.getByRole("button", { name: "Reset Speech" }));
  await waitFor(() => expect(calls).toContainEqual({ method: "PATCH", path: "/api/providers", body: { transcriber: null } }));
  fireEvent.click(screen.getByRole("button", { name: "Remove key" }));
  await waitFor(() => expect(calls).toContainEqual({ method: "DELETE", path: "/api/secrets/{ref}", params: { path: { ref: "ai/anthropic" } } }));
  validateFails = true;
  fireEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(useToasts.getState().items.at(-1)?.message).toBe("Couldn't check the key. Try again."));
  expect(screen.queryByText("Key was rejected")).toBeNull();
  expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
  validateFails = false;
  fireEvent.click(screen.getByRole("button", { name: "Project settings" }));
  expect(await screen.findByText("project settings")).toBeInTheDocument();
});
