import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { cardName, type EditCardData } from "@/features/edits/model";
import { ACTIVE, latest as latestRender, renderFile, renderStatusText, type RenderRow } from "@/lib/renders";
import { useToasts } from "@/lib/toasts";

import { defaultPair, type CompareData, type VersionRow } from "./model";
import { VersionsView, type SidePreview } from "./VersionsView";

const POLL_MS = 2000;

/** S18 Versions (`/p/:pid/edits/:eid/versions?a=&b=`): browse, compare two versions side
 * by side, and revert (ADR 0083, 0090). */
export function VersionsScreen() {
  const { pid = "", eid = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);

  const cards = useQuery({
    queryKey: ["edits", pid],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/edits", { params: { path: { pid }, query: { limit: 200 } } })).data as unknown as { items: EditCardData[] }).items,
  });
  const card = cards.data?.find((c) => c.edit_id === eid);
  const versions = useQuery({
    queryKey: ["edit-versions", eid, "rows"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/edits/{eid}/versions", { params: { path: { eid } } });
      if (error || !data) throw new Error("versions");
      return (data as unknown as { items: VersionRow[] }).items;
    },
  });
  const rows = versions.data;
  const newest = rows?.length ? Math.max(...rows.map((v) => v.version)) : undefined;
  const asked: [number, number] | null = params.get("a") && params.get("b") ? [Number(params.get("a")), Number(params.get("b"))] : null;
  const known = (v: number) => rows?.some((r) => r.version === v) ?? false;
  const pair = asked && known(asked[0]) && known(asked[1]) && asked[0] !== asked[1] ? ([Math.min(...asked), Math.max(...asked)] as [number, number]) : rows ? defaultPair(rows) : null;

  const compare = useQuery({
    queryKey: ["edit-compare", eid, pair?.[0], pair?.[1]],
    enabled: pair !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/edits/{eid}/compare", { params: { path: { eid }, query: { a: pair![0], b: pair![1] } } });
      if (error || !data) throw new Error("compare");
      return data as unknown as CompareData;
    },
  });

  const sides = useQueries({
    queries: (pair ?? []).map((v) => ({
      queryKey: ["edit", eid, v],
      queryFn: async () => (await api.GET("/api/edits/{eid}/versions/{version}", { params: { path: { eid, version: v } } })).data as unknown as { renders: RenderRow[] },
      refetchInterval: (q: { state: { data?: { renders: RenderRow[] } } }) => (q.state.data?.renders.some((r) => ACTIVE.has(r.status)) ? POLL_MS : false),
    })),
  });
  const render = useMutation({
    mutationFn: async (version: number) => {
      const { error } = await api.POST("/api/renders", { body: { edit_id: eid, version, final: false, codec: "h264" } });
      if (error) throw new Error("render");
    },
    onSuccess: (_, v) => void qc.invalidateQueries({ queryKey: ["edit", eid, v] }),
    onError: () => toast({ kind: "error", message: "Couldn't start the preview. Try again." }),
  });
  const previews: Record<number, SidePreview> = {};
  (pair ?? []).forEach((v, i) => {
    const row = sides[i]?.data ? latestRender(sides[i]!.data!.renders, "preview") : undefined;
    previews[v] =
      row?.status === "done"
        ? { url: renderFile(pid, row.render_id) }
        : row && ACTIVE.has(row.status)
          ? { status: renderStatusText(row) }
          : { onRender: render.isPending ? undefined : () => render.mutate(v) };
  });

  const revert = useMutation({
    mutationFn: async (to: number) => {
      const { data, error } = await api.POST("/api/edits/{eid}/revert", { params: { path: { eid } }, body: { version: to } });
      if (error || !data) throw error ?? new Error("revert");
      return { made: (data as unknown as { version: number }).version, to };
    },
    onSuccess: async ({ made, to }) => {
      toast({ kind: "success", message: `Version ${made} created, the same as v${to}.` });
      for (const k of [["edit", eid], ["edits", pid], ["draft", eid], ["edit-findings", eid]]) void qc.invalidateQueries({ queryKey: k });
      await qc.invalidateQueries({ queryKey: ["edit-versions", eid] }); // the new one is known first
      setParams({ a: String(to), b: String(made) }, { replace: true });
    },
    onError: (e) => {
      const detail = (e as { detail?: unknown }).detail;
      toast({ kind: "error", message: typeof detail === "string" ? detail : "Couldn't revert. Try again." });
    },
  });

  return (
    <VersionsView
      title={card ? cardName(card) : "Edit"}
      versions={rows}
      error={versions.isError}
      onRetry={() => void versions.refetch()}
      pair={pair}
      compare={compare.data}
      compareError={compare.isError}
      previews={previews}
      reverting={revert.isPending}
      onSelect={(v) => {
        if (newest === undefined || !rows || rows.length < 2) return;
        const other = v === newest ? defaultPair(rows)![0] : newest;
        setParams({ a: String(Math.min(v, other)), b: String(Math.max(v, other)) }, { replace: true });
      }}
      onLatestPair={() => setParams({}, { replace: true })}
      onRevert={(v) => !revert.isPending && revert.mutate(v)}
      onBack={() => navigate(`/p/${pid}/edits/${eid}`)}
    />
  );
}
