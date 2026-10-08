import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { api } from "@/api/client";
import { useToasts } from "@/lib/toasts";

import { DiagnosticsView } from "./DiagnosticsView";
import { FILTERS, LIVE, type TaskDetail, type TaskRow, type TaskStatus } from "./model";

const POLL_MS = 3000;
const PAGE = 100;

/** S23 Diagnostics (`/diagnostics?status=&project=`; ADR 0054). Polls while a task runs. */
export function DiagnosticsScreen() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const asked = params.get("status");
  const filter: "all" | TaskStatus = FILTERS.some((f) => f.value === asked) ? (asked as TaskStatus) : "all";
  const project = params.get("project");
  // The selection belongs to one filter: back/forward to another clears it too.
  const [picked, setSelected] = useState<{ id: number; key: string } | null>(null);
  const viewKey = `${filter}|${project ?? ""}`;
  const selected = picked && picked.key === viewKey ? picked.id : null;
  const [exporting, setExporting] = useState(false);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: { id: string; name: string }[] } | undefined,
  });
  const pages = useInfiniteQuery({
    queryKey: ["diagnostics", filter, project],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam }) => {
      const query: Record<string, string | number> = { limit: PAGE };
      if (filter !== "all") query.status = filter;
      if (project) query.project = project;
      if (pageParam !== undefined) query.cursor = pageParam;
      const { data, error } = await api.GET("/api/diagnostics/tasks", { params: { query } });
      if (error || !data) throw new Error("tasks");
      return data as unknown as { items: TaskRow[]; next_cursor: number | null };
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: (q) => (q.state.data?.pages.some((pg) => pg.items.some((r) => LIVE.has(r.status))) ? POLL_MS : false),
  });
  const rows = useMemo(() => pages.data?.pages.flatMap((pg) => pg.items), [pages.data]);
  const detail = useQuery({
    queryKey: ["diagnostics-task", selected],
    enabled: selected !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/diagnostics/tasks/{tid}", { params: { path: { tid: selected! } } });
      if (error || !data) throw new Error("task");
      return data as unknown as TaskDetail;
    },
    refetchInterval: (q) => (q.state.data && LIVE.has(q.state.data.status) ? POLL_MS : false),
  });

  const act = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: "retry" | "skip" }) => {
      const res =
        action === "retry"
          ? await api.POST("/api/diagnostics/tasks/{tid}/retry", { params: { path: { tid: id } } })
          : await api.POST("/api/diagnostics/tasks/{tid}/skip", { params: { path: { tid: id } } });
      if (res.error) {
        const d = (res.error as { detail?: unknown }).detail;
        throw new Error(typeof d === "string" ? d : action === "retry" ? "Couldn't retry this task. Try again." : "Couldn't skip this task. Try again.");
      }
      return action;
    },
    onSuccess: (action) => toast({ kind: "info", message: action === "retry" ? "Running it again." : "Skipped. Its job carries on without it." }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["diagnostics"] });
      void qc.invalidateQueries({ queryKey: ["diagnostics-task"] });
    },
    onError: (e) => toast({ kind: "error", message: e.message }),
  });

  const exportBundle = async () => {
    setExporting(true);
    try {
      const { data, error } = await api.POST("/api/diagnostics/bundle", { parseAs: "blob" });
      if (error || !data) throw new Error("bundle");
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "mosaic-diagnostics.zip";
      document.body.append(a); // WebKit (the desktop webview) needs it in the page
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000); // after the download has started
    } catch {
      toast({ kind: "error", message: "Couldn't prepare the bundle. Try again." });
    } finally {
      setExporting(false);
    }
  };

  const set = (next: { status?: string; project?: string | null }) => {
    const q = new URLSearchParams(params);
    if (next.status !== undefined) {
      if (next.status === "all") q.delete("status");
      else q.set("status", next.status);
    }
    if (next.project !== undefined) {
      if (next.project) q.set("project", next.project);
      else q.delete("project");
    }
    setParams(q);
  };

  return (
    <DiagnosticsView
      filter={filter}
      onFilter={(f) => set({ status: f })}
      projects={projects.data?.items ?? []}
      project={project}
      onProject={(id) => set({ project: id })}
      rows={rows}
      error={pages.isError && !rows}
      onRetryLoad={() => void pages.refetch()}
      hasMore={pages.hasNextPage}
      onMore={() => void pages.fetchNextPage()}
      loadingMore={pages.isFetchingNextPage}
      selected={selected}
      onSelect={(id) => setSelected({ id, key: viewKey })}
      detail={detail.data}
      detailError={detail.isError && !detail.data}
      onRetryTask={(id) => act.mutate({ id, action: "retry" })}
      onSkipTask={(id) => act.mutate({ id, action: "skip" })}
      acting={act.isPending}
      onExport={() => void exportBundle()}
      exporting={exporting}
    />
  );
}
