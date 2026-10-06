import { useInfiniteQuery, useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "@/api/client";
import { CLIP_UPDATED, type ClipUpdated } from "@/lib/activity";
import { useToasts } from "@/lib/toasts";

import { optimistic, optimisticClip, type ClipDetail, type DecisionChange, type Filters, type Grouping, type LibraryPage } from "./model";

export const PAGE = 120;

export function libraryKey(pid: string, group: Grouping, filters: Filters, showRejected: boolean) {
  return ["library", pid, group, filters, showRejected] as const;
}

/** The library, a page at a time in group order (keyset pages, ADR 0031). */
export function useLibrary(pid: string, group: Grouping, filters: Filters, showRejected: boolean) {
  return useInfiniteQuery({
    queryKey: libraryKey(pid, group, filters, showRejected),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: LibraryPage) => last.next_cursor ?? undefined,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/projects/{pid}/library", {
        params: {
          path: { pid },
          query: { group, limit: PAGE, cursor: pageParam, show_rejected: showRejected, ...filters },
        },
      });
      if (error) throw new Error("library");
      return data as unknown as LibraryPage;
    },
  });
}

/** Owner decisions on one clip or many: optimistic in every loaded library page, then
 * the server's truth (S10 acceptance: user style at once, and it persists). */
export function useDecide(pid: string) {
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const mutationKey = ["decide", pid];
  return useMutation({
    mutationKey,
    mutationFn: async ({ ids, change }: { ids: number[]; change: DecisionChange }) => {
      if (ids.length === 1) {
        const { error } = await api.PATCH("/api/projects/{pid}/clips/{aid}/decision", {
          params: { path: { pid, aid: ids[0]! } },
          body: change,
        });
        if (error) throw new Error("decision");
      } else {
        const { error } = await api.POST("/api/projects/{pid}/decisions/bulk", {
          params: { path: { pid } },
          body: { asset_ids: ids, ...change },
        });
        if (error) throw new Error("decision");
      }
    },
    onMutate: async ({ ids, change }) => {
      await qc.cancelQueries({ queryKey: ["library", pid] });
      await qc.cancelQueries({ queryKey: ["clip", pid] });
      const before = [
        ...qc.getQueriesData<InfiniteData<LibraryPage>>({ queryKey: ["library", pid] }),
        ...ids.flatMap((id) => qc.getQueriesData<ClipDetail>({ queryKey: ["clip", pid, id] })),
      ] as [readonly unknown[], unknown][];
      const wanted = new Set(ids);
      for (const id of ids) {
        // The inspector shows the owner's decision at once too (S10 acceptance).
        qc.setQueriesData<ClipDetail>({ queryKey: ["clip", pid, id] }, (c) => c && optimisticClip(c, change));
      }
      qc.setQueriesData<InfiniteData<LibraryPage>>({ queryKey: ["library", pid] }, (data) =>
        data && {
          ...data,
          pages: data.pages.map((p) => ({
            ...p,
            items: p.items.map((it) => (wanted.has(it.asset_id) ? optimistic(it, change) : it)),
          })),
        },
      );
      return { before };
    },
    onError: (_e, _v, ctx) => {
      for (const [key, data] of ctx?.before ?? []) qc.setQueryData(key, data);
      toast({ kind: "error", message: "Couldn't save that decision. Try again." });
    },
    onSettled: () => {
      // Refetch once the last of overlapping decisions settles, so an early refetch never
      // undoes a later optimistic change.
      if (qc.isMutating({ mutationKey }) > 1) return;
      void qc.invalidateQueries({ queryKey: ["library", pid] });
      void qc.invalidateQueries({ queryKey: ["clip", pid] });
    },
  });
}

/** Refetches the library and open clips when decisions change elsewhere (SSE). */
export function useClipUpdates(pid: string) {
  const qc = useQueryClient();
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const on = (e: Event) => {
      const d = (e as CustomEvent<ClipUpdated>).detail;
      if (d.project_id !== pid) return;
      if (d.asset_id !== null) void qc.invalidateQueries({ queryKey: ["clip", pid, d.asset_id] });
      clearTimeout(timer);
      timer = setTimeout(() => void qc.invalidateQueries({ queryKey: ["library", pid] }), 300);
    };
    window.addEventListener(CLIP_UPDATED, on);
    return () => {
      clearTimeout(timer);
      window.removeEventListener(CLIP_UPDATED, on);
    };
  }, [pid, qc]);
}
