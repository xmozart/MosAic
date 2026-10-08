import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api } from "@/api/client";
import { useMode } from "@/lib/mode";
import { useTheme } from "@/lib/theme";
import { useToasts } from "@/lib/toasts";

import { AppSettingsView } from "./AppSettingsView";
import type { AppSettings, MediaRoot, ProviderOptions, Providers, SystemInfo } from "./model";

/** A server message fit for a toast: plain text only (never a validation list or a CLI
 * hint); else ``fallback``. */
function plain(error: unknown, fallback: string): string {
  const d = (error as { detail?: unknown } | undefined)?.detail;
  return typeof d === "string" && d.length < 160 && !d.includes("mosaic config") ? d : fallback;
}

/** S22 App settings (`/settings`; ADR 0053). Keys are typed once and sent; nothing about
 * them is kept here (invariant 11). */
export function AppSettingsScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const theme = useTheme();
  const mode = useMode();
  const [checks, setChecks] = useState<Record<string, "ok" | "invalid" | "checking">>({});

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: async () => (await api.GET("/api/settings")).data as unknown as AppSettings,
  });
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: async () => (await api.GET("/api/providers")).data as unknown as Providers,
  });
  const options = useQuery({
    queryKey: ["provider-options"],
    staleTime: Infinity,
    queryFn: async () => (await api.GET("/api/providers/options")).data as unknown as ProviderOptions,
  });
  const system = useQuery({
    queryKey: ["system-info"],
    queryFn: async () => (await api.GET("/api/system/info")).data as unknown as SystemInfo,
  });
  const roots = useQuery({
    queryKey: ["media-roots"],
    enabled: mode === "server",
    queryFn: async () => ((await api.GET("/api/admin/media-roots")).data as unknown as { items: MediaRoot[] }).items,
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: { id: string; name: string }[] } | undefined,
  });
  const recent = projects.data?.items[0];

  const setting = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const { error } = await api.PATCH("/api/settings", { body: { [key]: value } as Record<string, never> });
      if (error) throw new Error("setting");
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["settings"] }),
    onError: () => toast({ kind: "error", message: "That value isn't valid. Nothing was changed." }),
  });
  const provider = useMutation({
    mutationFn: async ({ task, choice }: { task: string; choice: { provider: string; model: string } | null }) => {
      const { error } = await api.PATCH("/api/providers", { body: { [task]: choice } as Record<string, never> });
      if (error) throw new Error(plain(error, "That provider or model can't do this task. Nothing was changed."));
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["providers"] }),
    onError: (e) => toast({ kind: "error", message: e.message }),
  });
  const addRoot = useMutation({
    mutationFn: async ({ path, label }: { path: string; label: string }) => {
      const { error } = await api.POST("/api/admin/media-roots", { body: { path, label: label || null } });
      if (error) throw new Error(plain(error, "Couldn't add that folder. Check that it exists on the server."));
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["media-roots"] }),
    onError: (e) => toast({ kind: "error", message: e.message }),
  });
  const removeRoot = useMutation({
    mutationFn: async (r: MediaRoot) => {
      const { error } = await api.DELETE("/api/admin/media-roots/{root_id}", { params: { path: { root_id: r.id } } });
      if (error) throw new Error("root");
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["media-roots"] }),
    onError: () => toast({ kind: "error", message: "Couldn't remove that folder." }),
  });

  const localOnly = Boolean(settings.data?.["ai.local_only"]?.value);
  const saveKey = async (prov: string, value: string) => {
    const { error } = await api.PUT("/api/secrets/{ref}", { params: { path: { ref: `ai/${prov}` } }, body: { value } });
    if (error) {
      toast({ kind: "error", message: "The key wasn't saved. Check it and try again." });
      throw new Error("key"); // SecretField asks for it again; nothing is kept
    }
    setChecks(({ [prov]: _old, ...rest }) => rest);
    await qc.invalidateQueries({ queryKey: ["providers"] });
    if (!localOnly) void validate(prov); // Local only sends nothing, not even a check
  };
  const validate = async (prov: string) => {
    setChecks((c) => ({ ...c, [prov]: "checking" }));
    try {
      const { data, error } = await api.POST("/api/secrets/{ref}/validate", { params: { path: { ref: `ai/${prov}` } } });
      if (error || !data) throw new Error("check");
      const ok = Boolean((data as { ok?: boolean }).ok);
      setChecks((c) => ({ ...c, [prov]: ok ? "ok" : "invalid" }));
    } catch {
      // Not a verdict on the key: the check itself didn't happen.
      setChecks(({ [prov]: _old, ...rest }) => rest);
      toast({ kind: "error", message: "Couldn't check the key. Try again." });
    }
  };
  const removeKey = useMutation({
    mutationFn: async (prov: string) => {
      const { error } = await api.DELETE("/api/secrets/{ref}", { params: { path: { ref: `ai/${prov}` } } });
      if (error) throw new Error("remove");
      return prov;
    },
    onSuccess: (prov) => {
      setChecks(({ [prov]: _old, ...rest }) => rest);
      toast({ kind: "info", message: "Key removed. A key the server provides, if any, is used again." });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["providers"] }),
    onError: () => toast({ kind: "error", message: "Couldn't remove the key. Try again." }),
  });

  return (
    <AppSettingsView
      theme={theme.choice}
      onTheme={theme.set}
      settings={settings.data}
      onSetting={(key, value) => setting.mutate({ key, value })}
      providers={providers.data}
      options={options.data}
      onProvider={(task, choice) => provider.mutate({ task, choice })}
      keyChecks={checks}
      onSaveKey={saveKey}
      onValidateKey={(p) => void validate(p)}
      onRemoveKey={(p) => removeKey.mutate(p)}
      system={system.data}
      roots={mode === "server" && roots.isSuccess ? roots.data : undefined}
      onAddRoot={(path, label) => addRoot.mutate({ path, label })}
      onRemoveRoot={(r) => removeRoot.mutate(r)}
      onDiagnostics={() => navigate("/diagnostics")}
      trip={recent ? { name: recent.name, onOpen: () => navigate(`/p/${recent.id}/settings`) } : undefined}
    />
  );
}
