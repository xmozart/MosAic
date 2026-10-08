import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router";

import { api } from "@/api/client";
import type { Placement } from "@/components/system/PlacementBadge";
import type { Settings } from "@/features/analysis/model";
import type { TripContext } from "@/features/context/model";
import { ClockCheckDialog } from "@/features/inventory/ClockCheckDialog";
import { formatBytes } from "@/lib/format";
import { useToasts } from "@/lib/toasts";

import type { DeviceSummary, StorageData } from "./model";
import { ProjectSettingsView } from "./ProjectSettingsView";

const POLL_MS = 2000;

interface Row {
  id: string;
  name: string;
  folder?: { root: string | null; path: string | null };
  placement: string;
  fs_class: string;
}

function placementOf(row: Row): Placement {
  if (row.placement === "split") return row.fs_class === "cloud_synced" ? "split_icloud" : "split_nas";
  if (row.placement === "external") return "separate";
  return "in_folder";
}

/** S21 Project settings (`/p/:pid/settings`; ADR 0052). */
export function ProjectSettingsScreen() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const { readOnly } = useOutletContext<{ readOnly?: boolean }>() ?? {};
  const [clocks, setClocks] = useState(false);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: Row[] } | undefined,
  });
  const row = projects.data?.items.find((x) => x.id === pid);
  const settings = useQuery({
    queryKey: ["project-settings", pid, null],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/settings", { params: { path: { pid }, query: {} } })).data as unknown as { settings: Settings }).settings,
  });
  const devices = useQuery({
    queryKey: ["devices", pid],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/devices", { params: { path: { pid } } })).data as unknown as { devices: DeviceSummary[] }).devices,
  });
  const context = useQuery({
    queryKey: ["trip-context", pid],
    queryFn: async () => (await api.GET("/api/projects/{pid}/trip-context", { params: { path: { pid } } })).data as unknown as TripContext,
  });
  const storage = useQuery({
    queryKey: ["storage", pid],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/projects/{pid}/storage", { params: { path: { pid } } });
      if (error || !data) throw new Error("storage");
      return data as unknown as StorageData;
    },
    refetchInterval: (q) => (q.state.data?.clearing_job_id ? POLL_MS : false),
  });

  const rename = useMutation({
    mutationFn: async (name: string) => {
      const { error } = await api.PATCH("/api/projects/{pid}", { params: { path: { pid } }, body: { name } });
      if (error) throw new Error("rename");
    },
    onMutate: (name) => {
      // Shown at once (no flash of the old name while the list reloads).
      qc.setQueryData<{ items: Row[] }>(["projects"], (old) => old && { ...old, items: old.items.map((x) => (x.id === pid ? { ...x, name } : x)) });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["projects"] }),
    onError: () => toast({ kind: "error", message: "Couldn't rename the trip. Try again." }),
  });
  const setting = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const { error, response } = await api.PATCH("/api/projects/{pid}/settings", { params: { path: { pid } }, body: { values: { [key]: value } } });
      if (error) throw new Error(response.status === 409 ? "read-only" : "setting");
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["project-settings", pid] }),
    onError: (e) =>
      toast({
        kind: "error",
        message: e.message === "read-only" ? "This project is open read-only here, so its settings can't change." : "That value isn't valid. Nothing was changed.",
      }),
  });
  const clear = useMutation({
    mutationFn: async () => {
      const { error, response } = await api.POST("/api/projects/{pid}/storage/clear-cache", { params: { path: { pid } } });
      if (error) throw new Error(response.status === 409 ? "busy" : "clear");
    },
    onSuccess: () => toast({ kind: "info", message: `Clearing ${formatBytes(storage.data?.regenerable_bytes ?? 0)} of previews and render cache.` }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["storage", pid] }),
    onError: (e) =>
      toast({ kind: "error", message: e.message === "busy" ? "Wait until the running analysis or render finishes, then clear." : "Couldn't clear the files. Try again." }),
  });
  const remove = useMutation({
    mutationFn: async (confirm_name: string) => {
      const { error, response } = await api.DELETE("/api/projects/{pid}/workspace", { params: { path: { pid } }, body: { confirm_name } });
      if (error) {
        const detail = String((error as { detail?: string }).detail ?? "");
        if (response.status === 409 && /elsewhere|in use|open in MosAic/.test(detail)) throw new Error("busy");
        if (response.status === 409 && /read-only/.test(detail)) throw new Error("read-only");
        if (response.status === 409 && /running analysis or render/.test(detail)) throw new Error("working");
        throw new Error("remove");
      }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      toast({ kind: "success", message: "MosAic's data was removed. Your footage is untouched." });
      navigate("/");
    },
    onError: (e) =>
      toast({
        kind: "error",
        message:
          {
            busy: "This trip is open in MosAic elsewhere (another window, the server or a worker). Close it, or wait a minute, and try again.",
            "read-only": "This project is open read-only here, so its data can't be removed.",
            working: "Wait until the running analysis or render finishes, then try again.",
          }[e.message] ?? "Couldn't remove MosAic's data. Nothing was removed.",
      }),
  });

  return (
    <>
      <ProjectSettingsView
        name={row?.name ?? ""}
        folder={row?.folder?.path ?? ""}
        placement={row ? placementOf(row) : "in_folder"}
        readOnly={readOnly}
        onRename={(n) => rename.mutate(n)}
        settings={settings.data}
        onSetting={(key, value) => setting.mutate({ key, value })}
        onAnalysisSetup={() => navigate(`/p/${pid}/analyze`)}
        devices={devices.data}
        onCheckClocks={() => setClocks(true)}
        context={context.data}
        onEditContext={() => navigate(`/p/${pid}/context`)}
        storage={storage.data}
        clearing={clear.isPending || Boolean(storage.data?.clearing_job_id)}
        onClear={() => clear.mutate()}
        removing={remove.isPending}
        onRemove={(n) => remove.mutate(n)}
      />
      <ClockCheckDialog pid={pid} open={clocks} onOpenChange={(o) => {
        setClocks(o);
        if (!o) void qc.invalidateQueries({ queryKey: ["devices", pid] });
      }} />
    </>
  );
}
