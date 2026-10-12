import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { cardName, type EditCardData } from "@/features/edits/model";
import { ACTIVE, latest, renderFile } from "@/lib/renders";
import { useToasts } from "@/lib/toasts";

import type { EditVersionData, Finding, ReportData, VersionItem } from "./model";
import { PreviewView, type PreviewState } from "./PreviewView";

const POLL_MS = 2000;
const ENDED = new Set(["done", "failed", "cancelled"]);

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
      const { error } = await api.POST("/api/renders", { body: { edit_id: eid, version, final, codec: "h264" } });
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

  // Findings (M4; ADR 0081, 0089): the shown version's; fixes go to the latest.
  const findings = useQuery({
    queryKey: ["edit-findings", eid, version],
    enabled: version !== undefined,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/edits/{eid}/findings", { params: { path: { eid }, query: { version } } });
      if (error || !data) throw new Error("findings");
      const got = data as unknown as { items: Finding[]; applied?: Finding[] };
      // The findings whose fix made this version first ("Applied in vN"), then its own.
      return [...(got.applied ?? []), ...got.items];
    },
  });
  const newest = versions.data?.length ? Math.max(...versions.data.map((x) => x.version)) : undefined;
  const isLatest = asked === undefined || asked === newest;
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["edit", eid] });
    void qc.invalidateQueries({ queryKey: ["edits", pid] });
    void qc.invalidateQueries({ queryKey: ["edit-versions", eid] });
    void qc.invalidateQueries({ queryKey: ["edit-findings", eid] });
    void qc.invalidateQueries({ queryKey: ["draft", eid] });
  };
  const refused = (error: unknown, fallback: string) => {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    toast({ kind: "error", message: typeof detail === "string" && detail ? detail : fallback });
  };
  // Undo of a fix: a new version equal to the one it was applied to (ADR 0083).
  const revert = useMutation({
    mutationFn: async (to: number) => {
      const { error } = await api.POST("/api/edits/{eid}/revert", { params: { path: { eid } }, body: { version: to } });
      if (error) throw error;
    },
    onSuccess: () => {
      setParams({}, { replace: true });
      refresh();
    },
    onError: (e) => refused(e, "Couldn't undo that. Try again."),
  });
  // One "Version N created" toast at a time: an older Undo would drop the later fixes.
  const undoToast = useRef<number | null>(null);
  const dismiss = useToasts((s) => s.dismiss);
  const shown = (child: number, from: number, undo: boolean) => {
    setParams({}, { replace: true }); // the new version is the latest: show it
    refresh();
    if (undoToast.current !== null) dismiss(undoToast.current);
    undoToast.current = null;
    // While beats regenerate on top of the fixes, an undo would land under them: none.
    toast(undo ? { kind: "success", message: `Version ${child} created`, action: { label: "Undo", run: () => revert.mutate(from) } } : { kind: "success", message: `Fixes applied as version ${child}` });
    if (undo) undoToast.current = useToasts.getState().items.at(-1)?.id ?? null;
  };
  const apply = useMutation({
    mutationFn: async (which: string | null) => {
      const from = version!;
      const res = which
        ? await api.POST("/api/edits/{eid}/findings/{fid}/apply", { params: { path: { eid, fid: which } } })
        : await api.POST("/api/edits/{eid}/findings/apply-all", { params: { path: { eid } } });
      if (res.error || !res.data) throw res.error ?? new Error("apply");
      return { child: (res.data as unknown as { version: number }).version, from };
    },
    onSuccess: ({ child, from }) => shown(child, from, true),
    onError: (e) => {
      refused(e, "Couldn't apply that fix. Try again.");
      void findings.refetch();
    },
  });
  const ignore = useMutation({
    mutationFn: async (which: string | null) => {
      const res = which
        ? await api.POST("/api/edits/{eid}/findings/{fid}/ignore", { params: { path: { eid, fid: which } } })
        : await api.POST("/api/edits/{eid}/findings/ignore-all", { params: { path: { eid } } });
      if (res.error) throw res.error;
    },
    onSettled: () => void findings.refetch(),
    onError: (e) => refused(e, "Couldn't ignore that. Try again."),
  });
  const [fixJob, setFixJob] = useState<number | null>(null);
  const fixes = useMutation({
    mutationFn: async () => {
      const from = version!;
      const { data, error } = await api.POST("/api/edits/{eid}/findings/regenerate", { params: { path: { eid } } });
      if (error || !data) throw error ?? new Error("fixes");
      return { ...(data as unknown as { version: number | null; job_id: number | null; beats: string[] }), from };
    },
    onSuccess: (r) => {
      if (r.version !== null) shown(r.version, r.from, r.job_id === null);
      if (r.job_id !== null) {
        if (undoToast.current !== null) dismiss(undoToast.current); // no undo under the job
        undoToast.current = null;
        setFixJob(r.job_id);
        toast({ kind: "info", message: `Regenerating ${r.beats.length === 1 ? "the beat that still has issues" : `${r.beats.length} beats that still have issues`}. Your locked shots stay.` });
      }
    },
    onError: (e) => refused(e, "Couldn't regenerate. Try again."),
  });
  const job = useQuery({
    queryKey: ["job", fixJob],
    enabled: fixJob !== null,
    refetchInterval: (q) => (q.state.data && ENDED.has(q.state.data.state) ? false : POLL_MS),
    queryFn: async () => (await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: fixJob! } } })).data as unknown as { state: string; error: string | null },
  });
  const jobState = job.data?.state;
  const toldPaused = useRef(false);
  useEffect(() => {
    if (!fixJob || !jobState) return;
    if (jobState === "paused_cost_limit" && !toldPaused.current) {
      toldPaused.current = true;
      toast({ kind: "info", message: "The regeneration paused at its AI cost limit. You can resume it from Activity." });
    }
    if (!ENDED.has(jobState)) return;
    toldPaused.current = false;
    setFixJob(null);
    setParams({}, { replace: true });
    refresh();
    if (jobState === "done") toast({ kind: "success", message: "The regenerated version is ready." });
    else toast({ kind: "error", message: "The beats couldn't be regenerated." });
    // refresh and toast are stable in effect: they only invalidate and push.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobState, fixJob]);
  const fixing = apply.isPending || ignore.isPending || fixes.isPending || revert.isPending || fixJob !== null;

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
      onStoryboard={() => navigate(`/p/${pid}/edits/${eid}/storyboard`)}
      report={merged}
      reportError={report.isError && !merged}
      onRetryReport={() => void report.refetch()}
      onMoreRejected={() => void report.fetchNextPage()}
      loadingMore={report.isFetchingNextPage}
      busy={render.isPending || regenerate.isPending}
      findings={findings.data}
      findingsError={findings.isError}
      onRetryFindings={() => void findings.refetch()}
      latest={isLatest}
      fixing={fixing}
      onApplyFinding={(id) => apply.mutate(id)}
      onIgnoreFinding={(id) => ignore.mutate(id)}
      onApplyAll={() => apply.mutate(null)}
      onIgnoreAll={() => ignore.mutate(null)}
      onRegenerateWithFixes={() => fixes.mutate()}
    />
  );
}
