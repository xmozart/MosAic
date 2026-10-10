import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NO_KEY, OPTIONS, SETTINGS } from "@/features/app-settings/fixtures";

import { FirstRunGate } from "./FirstRunScreen";
import { FirstRunView } from "./FirstRunView";
import type { ModelRow } from "./model";

const MODELS: ModelRow[] = [
  { name: "whisper-medium", label: "Speech", capability: "transcriber", provider: "faster-whisper", model: "medium", bytes: 1_530_571_735, downloaded_bytes: 0, installed: false, needed: true, job: null },
  { name: "siglip-base", label: "Image understanding", capability: "embedder", provider: "siglip-onnx", model: "base", bytes: 815_550_726, downloaded_bytes: 815_550_726, installed: true, needed: true, job: null },
  { name: "whisper-large-v3", label: "Speech (large)", capability: "transcriber", provider: "faster-whisper", model: "large-v3", bytes: 3_090_835_702, downloaded_bytes: 0, installed: false, needed: false, job: null },
];

const calls: { method: string; path: string; body?: unknown; params?: unknown }[] = [];
let settings: Record<string, { value: unknown; source: string }> = { ...SETTINGS, "app.first_run_done": { value: false, source: "default" } };
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string) => {
      const data: Record<string, unknown> = {
        "/api/settings": settings,
        "/api/providers": NO_KEY,
        "/api/providers/options": OPTIONS,
        "/api/models/local": { items: MODELS },
      };
      return Promise.resolve(path in data ? { data: data[path] } : { error: { detail: "x" } });
    },
    PATCH: (path: string, o: { body: Record<string, unknown> }) => {
      calls.push({ method: "PATCH", path, body: o.body });
      if (path === "/api/settings" && "app.first_run_done" in o.body) settings = { ...settings, "app.first_run_done": { value: true, source: "user" } };
      return Promise.resolve({ data: {} });
    },
    PUT: (path: string, o: { body: unknown; params: unknown }) => {
      calls.push({ method: "PUT", path, body: o.body, params: o.params });
      return Promise.resolve({ data: { configured: true, last4: "WXYZ" } });
    },
    POST: (path: string, o: { params: unknown }) => {
      calls.push({ method: "POST", path, params: o.params });
      if (path.endsWith("/validate")) return Promise.resolve({ data: { ok: true } });
      return Promise.resolve({ data: { job_id: 7 } });
    },
  },
}));

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <FirstRunGate mode="desktop">
        <p>the app</p>
      </FirstRunGate>
    </QueryClientProvider>,
  );
}

describe("S1 First run", () => {
  beforeEach(() => {
    calls.length = 0;
    settings = { ...SETTINGS, "app.first_run_done": { value: false, source: "default" } };
  });

  it("walks welcome → AI and key → models, saving the provider for every cloud task", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Get started" }));
    expect(screen.getByRole("radio", { name: /Hybrid/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.change(screen.getByLabelText("Anthropic API key"), { target: { value: "sk-ant-first-run" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(calls).toContainEqual({ method: "PUT", path: "/api/secrets/{ref}", body: { value: "sk-ant-first-run" }, params: { path: { ref: "ai/anthropic" } } }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/secrets/{ref}/validate")).toBe(true));
    expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain("sk-ant-first-run");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Downloading on-device models")).toBeInTheDocument();
    expect(calls).toContainEqual({ method: "PATCH", path: "/api/settings", body: { "ai.local_only": false } });
    const providers = calls.find((c) => c.path === "/api/providers")?.body as Record<string, { provider: string; model: string }>;
    const cloud = OPTIONS.providers.anthropic!.capabilities.filter((c) => OPTIONS.presets.anthropic![c]);
    expect(Object.keys(providers).sort()).toEqual([...cloud].sort());
    expect(Object.values(providers).every((p) => p.provider === "anthropic")).toBe(true);
    // Only the needed, missing model starts; the installed and the unneeded ones don't.
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/models/local/{name}/download")).toHaveLength(1));
    expect(calls).toContainEqual({ method: "POST", path: "/api/models/local/{name}/download", params: { path: { name: "whisper-medium" } } });
    expect(screen.queryByText("Speech (large)")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continue while downloading" }));
    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(calls).toContainEqual({ method: "PATCH", path: "/api/settings", body: { "app.first_run_done": true } });
  });

  it("Local only lists what isn't available and saves no provider", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Get started" }));
    fireEvent.click(screen.getByRole("radio", { name: /Local only/ }));
    expect(screen.getByRole("region", { name: "Not available in Local only" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Anthropic API key")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Downloading on-device models")).toBeInTheDocument();
    expect(calls).toContainEqual({ method: "PATCH", path: "/api/settings", body: { "ai.local_only": true } });
    expect(calls.some((c) => c.path === "/api/providers")).toBe(false);
  });

  it("server mode and a finished first run go straight to the app", async () => {
    const qc = new QueryClient();
    const { unmount } = render(
      <QueryClientProvider client={qc}>
        <FirstRunGate mode="server">
          <p>the app</p>
        </FirstRunGate>
      </QueryClientProvider>,
    );
    expect(screen.getByText("the app")).toBeInTheDocument();
    unmount();
    settings = { ...settings, "app.first_run_done": { value: true, source: "user" } };
    mount();
    expect(await screen.findByText("the app")).toBeInTheDocument();
  });
});

describe("FirstRunView", () => {
  const props = {
    onStep: vi.fn(),
    mode: "hybrid" as const,
    onMode: () => {},
    providers: [{ id: "anthropic", label: "Anthropic" }],
    provider: "anthropic",
    onProvider: () => {},
    onSaveKey: async () => {},
    onValidateKey: () => {},
    models: MODELS,
    onRetry: vi.fn(),
    onFinish: () => {},
  };

  it("Enter continues and Esc goes back from wherever focus is, with valid markup", () => {
    const errors = vi.spyOn(console, "error");
    render(<FirstRunView {...props} step={2} />);
    fireEvent.keyDown(document.body, { key: "Enter" }); // focus on the page, as after Get started
    expect(props.onStep).toHaveBeenLastCalledWith(3);
    const radio = screen.getByRole("radio", { name: /Hybrid/ });
    radio.focus();
    fireEvent.keyDown(radio, { key: "Escape" });
    expect(props.onStep).toHaveBeenLastCalledWith(1);
    // Enter in the key field is the field's own (Save), never Continue.
    props.onStep.mockClear();
    fireEvent.keyDown(screen.getByLabelText("Anthropic API key"), { key: "Enter" });
    expect(props.onStep).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled(); // e.g. "<form> cannot contain a nested <form>"
    errors.mockRestore();
  });

  it("a paused download offers Retry; an invalid key says so", () => {
    const { rerender } = render(<FirstRunView {...props} step={3} models={[{ ...MODELS[0]!, job: { job_id: 4, state: "failed", pct: 30 } }]} />);
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    expect(props.onRetry).toHaveBeenCalledWith("whisper-medium");
    rerender(<FirstRunView {...props} step={2} keyStatus="invalid" />);
    expect(screen.getByText(/That key was refused/)).toBeInTheDocument();
  });
});
