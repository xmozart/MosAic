import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { media } from "@/lib/media";

import { EditsView } from "./EditsView";
import { otherLength, type EditCardData } from "./model";

const BUSY = new Set(["generating", "rendering"]);

/** S13 Edits (`/p/:pid/edits`). Polls while an edit is generating or rendering. */
export function EditsScreen() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const edits = useQuery({
    queryKey: ["edits", pid],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/projects/{pid}/edits", { params: { path: { pid }, query: { limit: 200 } } });
      if (error || !data) throw new Error("edits");
      return (data as unknown as { items: EditCardData[] }).items;
    },
    refetchInterval: (q) => (q.state.data?.some((e) => BUSY.has(e.status)) ? 2000 : false),
  });
  return (
    <EditsView
      items={edits.data}
      error={edits.isError}
      onRetry={() => void edits.refetch()}
      coverUrl={(sid) => media.frame(pid, sid)}
      renderLink={(e, children, className) => (
        <Link to={`/p/${pid}/edits/${e.edit_id}`} className={className}>
          {children}
        </Link>
      )}
      onCreate={() => navigate(`/p/${pid}/edits/new`)}
      onStartFrom={(s) => {
        const q = new URLSearchParams({ from: s.from.edit_id });
        if (s.kind === "duplicate") q.set("duration", String(otherLength(s.from.request.duration_s ?? 180)));
        else q.set("aspect", "9:16");
        navigate(`/p/${pid}/edits/new?${q.toString()}`);
      }}
    />
  );
}
