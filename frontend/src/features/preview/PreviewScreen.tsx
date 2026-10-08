import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { cardName, type EditCardData } from "@/features/edits/model";
import { ACTIVE, latest, renderFile } from "@/lib/renders";
import { useToasts } from "@/lib/toasts";

import type { EditVersionData, ReportData, VersionItem } from "./model";
import { PreviewView, type PreviewState } from "./PreviewView";

const POLL_MS = 2000;

/** S17 Preview (`/p/:pid/edits/:eid?v=`). Opening a version without a preview starts one
 * (ADR 0049); the page follows renders and generation while they run. */
export function PreviewScreen() {
  const { eid = "" } = useParams();
  // Another edit is another page: nothing (data, started previews) carries over.
  return <Preview key={eid} />;
}

function Preview() {
  const { pid = "", eid = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const asked = Number(params.get("v")) || undefined;

  const cards = useQuery({
    queryKey: ["edits", pid],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/edits", { params: { path: { pid }, query: { limit: 200 } } })).data as unknown as { items: EditCardData[] }).items,
    refetchInterval: (q) => (q.state.data?.find((c) => c.edit_id === eid)?.status === "generating" ? POLL_MS : false),
  });
  const card = cards.data?.find((c) => c.edit_id === eid);

  const edit = useQuery({
    queryKey: ["edit", eid, asked ?? "latest"],
    retry: false,
    placeholderData: keepPreviousData, // switching versions keeps the page, never a flash
    queryFn: async () => {
      const res = asked
        ? await api.GET("/api/edits/{eid}/versions/{version}", { params: { path: { eid, version: asked } } })
        : await api.GET("/api/edits/{eid}", { params: { path: { eid } } });
      if (res.error || !res.data) throw new Error(res.response.status === 404 ? "missing" : "edit");
      return res.data as unknown as EditVersionData;
    },
    refetchInterval: (q) => (q.state.data?.renders.some((r) => ACTIVE.has(r.status)) ? POLL_MS : false),
  });
  // A new version (a regenerate finished): load it, and the version list.
  const latestVersion = card?.latest_version ?? null;
  const seenVersion = useRef<number | null>(null);
  useEffect(() => {
    if (latestVersion === null) return;
    // The first value is what the edit query loaded already; only a newer one refetches.
    if (seenVersion.current !== null && seenVersion.current !== latestVersion) void qc.invalidateQueries({ queryKey: ["edit", eid] });
    seenVersion.current = latestVersion;
  }, [latestVersion, eid, qc]);
  const versions = useQuery({
    queryKey: ["edit-versions", eid, card?.latest_version ?? null],
    queryFn: async () => ((await api.GET("/api/edits/{eid}/versions", { params: { path: { eid } } })).data as unknown as { items: VersionItem[] }).items,
  });
  const version = edit.data?.version;

  const report = useInfiniteQuery({
    queryKey: ["edit-report", eid, version],
    enabled: version !== undefined,
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/edits/{eid}/report", { params: { path: { eid }, query: { version, rejected_offset: pageParam } } });
      if (error || !data) throw new Error("report");
      return data as unknown as ReportData;
    },
    getNextPageParam: (last) => {
      const next = last.rejected.offset + last.rejected.items.length;
      return next < last.rejected.total ? next : undefined;
    },
  });
  const merged = useMemo((): ReportData | undefined => {
    const pages = report.data?.pages;
    if (!pages?.length) return undefined;
    const first = pages[0]!;
    return { ...first, rejected: { ...first.rejected, items: pages.flatMap((x) => x.rejected.items) } };
  }, [report.data]);

  const render = useMutation({
    mutationFn: async (final: boolean) => {
      const { error } = await api.POST("/api/renders", { body: { edit_id: eid, version, final } });
      if (error) throw new Error("render");
      return final;
    },
    onSuccess: (final) => {
      void qc.invalidateQueries({ queryKey: ["edit", eid] });
      void qc.invalidateQueries({ queryKey: ["renders", pid] });
      if (final) toast({ kind: "info", message: "Rendering the final video. You can follow it in Exports." });
    },
    onError: () => toast({ kind: "error", message: "Couldn't start the render. Try again." }),
  });
  const regenerate = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/edits/{eid}/generate", { params: { path: { eid } } });
      if (error) throw new Error("generate");
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["edits", pid] }),
    onError: () => toast({ kind: "error", message: "Couldn't start the edit again. Try again." }),
  });

  // A version opened without any preview gets one, once per visit (rendering costs no
  // AI); only on fresh data, never on a cached page that predates a render. A preview the
  // owner deleted in S20 is made again the next time the version opens (ADR 0049).
  const started = useRef(new Set<string>());
  const renders = edit.data?.renders;
  const preview = renders ? latest(renders, "preview") : undefined;
  const fresh = edit.isSuccess && !edit.isFetching && !edit.isPlaceholderData;
  const startRender = render.mutate;
  useEffect(() => {
    if (!fresh || version === undefined || !renders || preview) return;
    const key = `${eid}/${version}`;
    if (started.current.has(key)) return;
    started.current.add(key);
    startRender(false);
  }, [fresh, eid, version, renders, preview, startRender]);

  let state: PreviewState;
  if (edit.data) state = { kind: "ready", edit: edit.data };
  else if (card?.status === "generating") state = { kind: "generating", pct: card.pct ?? 0 };
  else if (card?.status === "failed") state = { kind: "failed", error: card.error };
  else if (card?.status === "new") state = { kind: "new" };
  else if (edit.isError && edit.error.message !== "missing") state = { kind: "error" };
  else if (edit.isError && (cards.isSuccess || cards.isError)) state = { kind: "missing" };
  else state = { kind: "loading" };

  const final = renders ? latest(renders, "final") : undefined;
  return (
    <PreviewView
      title={card ? cardName(card) : (edit.data?.name ?? edit.data?.display_id ?? "Edit")}
      state={state}
      versions={versions.data ?? []}
      onVersion={(v) => setParams({ v: String(v) })}
      preview={preview}
      final={final}
      previewUrl={preview?.status === "done" ? renderFile(pid, preview.render_id) : undefined}
      finalDownloadUrl={final?.status === "done" ? renderFile(pid, final.render_id, true) : undefined}
      onRenderPreview={() => render.mutate(false)}
      onRenderFinal={() => render.mutate(true)}
      onRetryGenerate={() => regenerate.mutate()}
      onRetryLoad={() => void edit.refetch()}
      onBack={() => navigate(`/p/${pid}/edits`)}
      onExports={() => navigate(`/p/${pid}/exports`)}
      report={merged}
      reportError={report.isError && !merged}
      onRetryReport={() => void report.refetch()}
      onMoreRejected={() => void report.fetchNextPage()}
      loadingMore={report.isFetchingNextPage}
      busy={render.isPending || regenerate.isPending}
    />
  );
}
