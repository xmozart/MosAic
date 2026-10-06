import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import type { Estimate } from "@/lib/estimate";
import { useToasts } from "@/lib/toasts";

import { AnalysisSetupView } from "./AnalysisSetupView";
import { MODES, type Preset, type Settings } from "./model";

const ANALYSIS_KEYS = ["analysis.sample_interval", "analysis.tiles", "analysis.forced_max_shot", "analysis.proxy", "analysis.stt_model"];

interface Provider {
  provider: string;
  model: string;
}

/** S8 Analysis setup (`/p/:pid/analyze`). Advanced edits are saved as project settings
 * when the run starts; estimates follow them before that (ADR 0041). */
export function AnalysisSetupScreen() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const [picked, setPicked] = useState<Preset | null>(null);
  const [edits, setEdits] = useState<Record<string, unknown>>({});

  const stored = useQuery({
    queryKey: ["project-settings", pid, picked],
    queryFn: async () =>
      (await api.GET("/api/projects/{pid}/settings", { params: { path: { pid }, query: picked ? { mode: picked } : {} } })).data as unknown as {
        settings: Settings;
      },
    placeholderData: keepPreviousData, // no empty flash while another mode's values load
  });
  const selected: Preset = picked ?? ((stored.data?.settings["analysis.mode"]?.value as Preset | undefined) ?? "balanced");
  const settings = useMemo(() => {
    if (!stored.data) return undefined;
    const out: Settings = { ...stored.data.settings };
    for (const [k, value] of Object.entries(edits)) out[k] = { value, source: "project" };
    return out;
  }, [stored.data, edits]);

  const overrides = useMemo(() => {
    const o = Object.fromEntries(Object.entries(edits).filter(([k]) => ANALYSIS_KEYS.includes(k)));
    return Object.keys(o).length ? JSON.stringify(o) : undefined;
  }, [edits]);
  const deferred = useDebounced(overrides, 300); // one estimate round per pause in typing
  const estimates = useQueries({
    queries: MODES.map((m) => ({
      queryKey: ["estimate", pid, m.id, deferred],
      queryFn: async () =>
        (
          await api.GET("/api/projects/{pid}/analysis/estimate", {
            params: { path: { pid }, query: { mode: m.id, ...(deferred ? { overrides: deferred } : {}) } },
          })
        ).data as unknown as Estimate,
    })),
  });
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: async () => (await api.GET("/api/providers")).data as unknown as Record<string, Provider>,
  });
  const app = useQuery({
    queryKey: ["settings"],
    queryFn: async () => (await api.GET("/api/settings")).data as unknown as Record<string, { value: unknown }>,
  });
  const system = useQuery({
    queryKey: ["system-info"],
    queryFn: async () => (await api.GET("/api/system/info")).data as unknown as { hardware: { cpu_model?: string | null; machine?: string } },
  });
  const model = (cap: string) => {
    const p = providers.data?.[cap];
    return p ? `${p.provider} · ${p.model}` : "…";
  };

  const start = useMutation({
    mutationFn: async () => {
      const values = { ...edits, "analysis.mode": selected };
      const saved = await api.PATCH("/api/projects/{pid}/settings", { params: { path: { pid } }, body: { values } });
      if (saved.error) throw new Error("settings");
      const run = await api.POST("/api/projects/{pid}/analysis-runs", { params: { path: { pid } }, body: { mode: selected } });
      if (run.error || !run.data) throw new Error("run");
      return (run.data as { job_id: number }).job_id;
    },
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/p/${pid}/analysis?job=${job}`);
    },
    onError: (e) =>
      toast({
        kind: "error",
        message: e.message === "settings" ? "Some Advanced settings aren't valid. Check them and try again." : "Couldn't start the analysis. Try again.",
      }),
  });

  const onEdit = async (key: string, value: unknown) => {
    if (value !== null) {
      setEdits((e) => ({ ...e, [key]: value }));
      return;
    }
    setEdits(({ [key]: _gone, ...rest }) => rest);
    if (stored.data?.settings[key]?.source === "project") {
      // Resetting a saved value: clear it now so the mode's own value shows.
      const { error } = await api.PATCH("/api/projects/{pid}/settings", { params: { path: { pid } }, body: { values: { [key]: null } } });
      if (error) toast({ kind: "error", message: "Couldn't reset that setting. Try again." });
      void qc.invalidateQueries({ queryKey: ["project-settings", pid] });
    }
  };

  const hw = system.data?.hardware;
  return (
    <AnalysisSetupView
      selected={selected}
      onSelect={setPicked}
      estimates={Object.fromEntries(MODES.map((m, i) => [m.id, estimates[i]?.data]).filter(([, e]) => e))}
      settings={settings}
      edited={new Set(Object.keys(edits))}
      onEdit={(k, val) => void onEdit(k, val)}
      sceneModel={model("vision")}
      storyModel={model("planner")}
      device={`Auto · ${hw?.cpu_model ?? hw?.machine ?? "this computer"}`}
      localOnly={Boolean(app.data?.["ai.local_only"]?.value)}
      starting={start.isPending}
      onBack={() => navigate(`/p/${pid}/context`)}
      onAnalyze={() => start.mutate()}
    />
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}
