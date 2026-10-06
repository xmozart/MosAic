import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { media } from "@/lib/media";

import { SearchView, type SearchItem, type SearchMode } from "./SearchView";

/** S12 Search (`/p/:pid/search?q=&mode=`). / focuses the search; Enter runs it; Esc clears. */
export function SearchScreen() {
  const { pid = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const q = params.get("q") ?? "";
  const asked = params.get("mode");
  const mode: SearchMode = asked === "visual" || asked === "speech" ? asked : "all";
  const box = useRef<HTMLInputElement>(null);
  const results = useQuery({
    queryKey: ["search", pid, q, mode],
    enabled: q.length > 0,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/projects/{pid}/search", { params: { path: { pid }, query: { q, mode, limit: 100 } } });
      if (error || !data) throw new Error("search");
      return data as unknown as { items: SearchItem[]; visual: "ok" | "unavailable" | "off" };
    },
  });
  const suggestions = useQuery({
    queryKey: ["search-suggestions", pid],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/search/suggestions", { params: { path: { pid } } })).data as unknown as { suggestions: string[] }).suggestions,
  });
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.key !== "/" || el?.closest("input, textarea, [role=dialog]")) return;
      e.preventDefault();
      box.current?.focus();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);
  const set = (next: { q?: string; mode?: SearchMode }) => setParams({ q: next.q ?? q, mode: next.mode ?? mode });
  return (
    <SearchView
      key={q}
      ref={box}
      query={q}
      mode={mode}
      items={!q || results.isPending || results.isPlaceholderData ? undefined : results.data?.items}
      error={Boolean(q) && results.isError}
      onRetry={() => void results.refetch()}
      visual={results.data?.visual}
      suggestions={suggestions.data ?? []}
      frameUrl={(sid) => media.frame(pid, sid)}
      onSearch={(text) => set({ q: text })}
      onMode={(m) => set({ mode: m })}
      onOpen={(it) => navigate(`/p/${pid}/clips/${it.asset_id}`)}
    />
  );
}
