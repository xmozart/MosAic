import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { api } from "@/api/client";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import type { AppSettings, ProviderOptions, Providers } from "@/features/app-settings/model";
import { PROVIDER_LABEL } from "@/features/app-settings/model";
import { useToasts } from "@/lib/toasts";

import { FirstRunView, type AiMode, type FirstRunStep } from "./FirstRunView";
import { FIRST_RUN_DONE, type ModelRow } from "./model";

const POLL_MS = 1000;
const DEFAULT_PROVIDER = "anthropic"; // ADR 0003

/** Desktop: S1 until the first run is finished (ADR 0059); then the app. */
export function FirstRunGate({ mode, children }: { mode: string; children: ReactNode }) {
  const settings = useQuery({
    queryKey: ["settings"],
    enabled: mode === "desktop",
    queryFn: async () => (await api.GET("/api/settings")).data as unknown as AppSettings,
  });
  if (mode !== "desktop") return <>{children}</>;
  if (settings.isError && !settings.data) {
    return (
      <main className="flex min-h-full items-center justify-center bg-bg p-6">
        <div className="flex w-[400px] flex-col gap-3">
          <Banner kind="danger" action={<Button size="sm" onClick={() => void settings.refetch()}>Try again</Button>}>
            Couldn't load your settings.
          </Banner>
        </div>
      </main>
    );
  }
  if (!settings.data) return null;
  if (settings.data[FIRST_RUN_DONE]?.value === true) return <>{children}</>;
  return <FirstRunScreen />;
}

/** S1 First run (`docs/ui/screens/S01-first-run.md`). */
export function FirstRunScreen() {
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const [step, setStep] = useState<FirstRunStep>(1);
  const [mode, setMode] = useState<AiMode>("hybrid");
  const [provider, setProvider] = useState(DEFAULT_PROVIDER);
  const [check, setCheck] = useState<"ok" | "invalid" | "checking" | undefined>();

  const options = useQuery({
    queryKey: ["provider-options"],
    staleTime: Infinity,
    queryFn: async () => (await api.GET("/api/providers/options")).data as unknown as ProviderOptions,
  });
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: async () => (await api.GET("/api/providers")).data as unknown as Providers,
  });
  const models = useQuery({
    queryKey: ["models-local"],
    enabled: step === 3,
    queryFn: async () => ((await api.GET("/api/models/local")).data as unknown as { items: ModelRow[] }).items,
    refetchInterval: (q) => (q.state.data?.some((m) => m.needed && !m.installed && m.job) ? POLL_MS : false),
  });

  const cloud = Object.entries(options.data?.providers ?? {})
    .filter(([, p]) => p.mode === "cloud")
    .map(([id]) => ({ id, label: PROVIDER_LABEL[id] ?? id }));
  const key = Object.values(providers.data ?? {}).find((p) => p.provider === provider)?.key;

  // Step 3 starts every needed download once (a download already running is reused).
  const started = useRef(false);
  const start = useMutation({
    mutationFn: async (name: string) => {
      const { error } = await api.POST("/api/models/local/{name}/download", { params: { path: { name } } });
      if (error) throw new Error("download");
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["models-local"] }),
    onError: () => toast({ kind: "error", message: "Couldn't start the download. Check your connection and try again." }),
  });
  useEffect(() => {
    if (step !== 3 || started.current || !models.data) return;
    started.current = true;
    for (const m of models.data) if (m.needed && !m.installed && !m.job) start.mutate(m.name);
  }, [step, models.data, start]);

  const applyChoices = async () => {
    const local = mode === "local";
    const s = await api.PATCH("/api/settings", { body: { "ai.local_only": local } as unknown as Record<string, never> });
    if (s.error) throw new Error("settings");
    if (local) return;
    // The chosen provider for every cloud task it serves, with its preset models (S1 acceptance).
    const preset = options.data?.presets[provider] ?? {};
    const caps = options.data?.providers[provider]?.capabilities ?? [];
    const body = Object.fromEntries(caps.filter((c) => preset[c]).map((c) => [c, { provider, model: preset[c] }]));
    const p = await api.PATCH("/api/providers", { body: body as Record<string, never> });
    if (p.error) throw new Error("providers");
    await qc.invalidateQueries({ queryKey: ["providers"] });
  };

  const finish = useMutation({
    mutationFn: async () => {
      const { error } = await api.PATCH("/api/settings", { body: { [FIRST_RUN_DONE]: true } as unknown as Record<string, never> });
      if (error) throw new Error("finish");
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["settings"] }),
    onError: () => toast({ kind: "error", message: "Couldn't save your choices. Try again." }),
  });

  const saveKey = async (value: string) => {
    const { error } = await api.PUT("/api/secrets/{ref}", { params: { path: { ref: `ai/${provider}` } }, body: { value } });
    if (error) {
      setCheck(undefined); // not saved is not refused: SecretField says it wasn't saved
      throw new Error("key"); // SecretField asks for it again; nothing is kept
    }
    await qc.invalidateQueries({ queryKey: ["providers"] });
    void validate();
  };
  const validate = async () => {
    setCheck("checking");
    const { data, error } = await api.POST("/api/secrets/{ref}/validate", { params: { path: { ref: `ai/${provider}` } } });
    if (error || !data) {
      setCheck(undefined);
      toast({ kind: "error", message: "Couldn't check the key. Try again." });
      return;
    }
    setCheck((data as { ok?: boolean }).ok ? "ok" : "invalid");
  };

  return (
    <FirstRunView
      step={step}
      onStep={(next) => {
        if (step === 2 && next === 3) {
          applyChoices()
            .then(() => setStep(3))
            .catch(() => toast({ kind: "error", message: "Couldn't save your choices. Try again." }));
          return;
        }
        if (step === 3) started.current = false; // back: the choices may need other models
        setStep(next);
      }}
      mode={mode}
      onMode={setMode}
      providers={cloud.length ? cloud : [{ id: DEFAULT_PROVIDER, label: PROVIDER_LABEL[DEFAULT_PROVIDER] ?? "Anthropic" }]}
      provider={provider}
      onProvider={(id) => {
        setProvider(id);
        setCheck(undefined);
      }}
      keyLast4={key?.last4 ?? undefined}
      keyStatus={check === "checking" ? undefined : check}
      validating={check === "checking"}
      onSaveKey={saveKey}
      onValidateKey={() => void validate()}
      models={models.data}
      onRetry={(name) => start.mutate(name)}
      onFinish={() => finish.mutate()}
      finishing={finish.isPending}
    />
  );
}
