import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { media } from "@/lib/media";
import { ACTIVE, renderFile, type RenderRow } from "@/lib/renders";
import { useToasts } from "@/lib/toasts";

import { ExportsView } from "./ExportsView";

const POLL_MS = 2000;
const PAGE = 50;

interface Page {
  items: RenderRow[];
  next_cursor: number | null;
  folder: string;
}

/** S20 Exports (`/p/:pid/exports`): the project's renders, newest first; polls while one runs. */
export function ExportsScreen() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());

  const fetchPage = async (cursor?: number) => {
    const { data, error } = await api.GET("/api/projects/{pid}/renders", {
      params: { path: { pid }, query: { limit: PAGE, ...(cursor !== undefined ? { cursor } : {}) } },
    });
    if (error || !data) throw new Error("renders");
    return data as unknown as Page;
  };
  const pages = useInfiniteQuery({
    queryKey: ["renders", pid],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // Running renders are new, so on the first page, which `live` polls alone. Only a
    // running row further down (rare) makes every loaded page poll.
    refetchInterval: (q) => (q.state.data?.pages.slice(1).some((pg) => pg.items.some((r) => ACTIVE.has(r.status))) ? POLL_MS : false),
  });
  const firstActive = Boolean(pages.data?.pages[0]?.items.some((r) => ACTIVE.has(r.status)));
  const live = useQuery({
    queryKey: ["renders", pid, "live"],
    enabled: firstActive,
    queryFn: async () => {
      const page = await fetchPage();
      // The last running render ended: the loaded pages catch up once.
      if (!page.items.some((r) => ACTIVE.has(r.status))) void qc.invalidateQueries({ queryKey: ["renders", pid], exact: true });
      return page;
    },
    refetchInterval: (q) => (q.state.data?.items.some((r) => ACTIVE.has(r.status)) ?? true ? POLL_MS : false),
  });
  const items = useMemo(() => {
    if (!pages.data) return undefined;
    const [first, ...rest] = pages.data.pages;
    const head = firstActive && live.data && live.dataUpdatedAt >= pages.dataUpdatedAt ? live.data : first;
    const seen = new Set<number>();
    return [head!, ...rest].flatMap((pg) => pg.items).filter((r) => !seen.has(r.render_id) && Boolean(seen.add(r.render_id)));
  }, [pages.data, pages.dataUpdatedAt, live.data, live.dataUpdatedAt, firstActive]);

  const act = useMutation({
    mutationFn: async ({ r, action }: { r: RenderRow; action: "cancel" | "rerender" | "delete" }) => {
      setBusy((b) => new Set(b).add(r.render_id));
      const path = { pid, rid: r.render_id };
      const res =
        action === "delete"
          ? await api.DELETE("/api/projects/{pid}/renders/{rid}/file", { params: { path } })
          : await api.POST("/api/projects/{pid}/renders/{rid}/{action}", { params: { path: { ...path, action } } });
      if (res.error) throw new Error(action);
    },
    onSettled: (_d, _e, v) => {
      setBusy((b) => {
        const next = new Set(b);
        next.delete(v.r.render_id);
        return next;
      });
      void qc.invalidateQueries({ queryKey: ["renders", pid] });
      void qc.invalidateQueries({ queryKey: ["edit"] });
      void qc.invalidateQueries({ queryKey: ["edits", pid] });
    },
    onError: (_e, v) =>
      toast({
        kind: "error",
        message: { cancel: "Couldn't cancel that render.", rerender: "Couldn't start the render again.", delete: "Couldn't delete that file." }[v.action] + " Try again.",
      }),
  });

  return (
    <ExportsView
      folder={pages.data?.pages[0]?.folder ?? null}
      items={items}
      error={pages.isError && !items}
      onRetry={() => void pages.refetch()}
      hasMore={pages.hasNextPage}
      loadingMore={pages.isFetchingNextPage}
      onMore={() => void pages.fetchNextPage()}
      coverUrl={(sid) => media.frame(pid, sid)}
      fileUrl={(r, download) => renderFile(pid, r.render_id, download)}
      onCancel={(r) => act.mutate({ r, action: "cancel" })}
      onRerender={(r) => act.mutate({ r, action: "rerender" })}
      onDeleteFile={(r) => act.mutate({ r, action: "delete" })}
      onEdits={() => navigate(`/p/${pid}/edits`)}
      busy={busy}
    />
  );
}

/** `/exports` (the rail's Exports outside a project): the most recently opened trip's. */
export function ExportsIndex() {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/projects");
      if (error || !data) throw new Error("projects");
      return data as unknown as { items: { id: string }[] };
    },
  });
  const first = projects.data?.items[0];
  if (first) return <Navigate to={`/p/${first.id}/exports`} replace />;
  if (projects.isFetched && !projects.data) {
    return (
      <div className="flex flex-1 flex-col gap-3 px-8 py-7">
        <h1 className="text-title text-text">Exports</h1>
        <Banner
          kind="danger"
          action={
            <Button size="sm" onClick={() => void projects.refetch()}>
              Try again
            </Button>
          }
        >
          We couldn't load your trips.
        </Banner>
      </div>
    );
  }
  if (!projects.isFetched) return <div aria-label="Loading" className="m-8 h-14 flex-1 animate-pulse rounded-md bg-surface-1" />;
  return (
    <div className="flex flex-1 flex-col gap-2 px-8 py-7">
      <h1 className="text-title text-text">Exports</h1>
      <p className="text-body text-text-muted">Open a trip to see its exports.</p>
    </div>
  );
}
