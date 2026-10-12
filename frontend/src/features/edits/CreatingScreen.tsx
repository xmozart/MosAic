import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { media } from "@/lib/media";
import { ACTIVE, latest, type RenderRow } from "@/lib/renders";

import { CreatingView } from "./CreatingView";
import type { CreatingJob, JobState } from "./creating";
import { cardName, type EditCardData } from "./model";

const POLL_MS = 1000;

/** The version's preview; one whose file was deleted counts as none: it is made again
 * (ADR 0049). */
function preview(rows: RenderRow[]): RenderRow | undefined {
  const row = latest(rows, "preview");
  return row?.status === "missing" ? undefined : row;
}

/** S15 Creating edit (`/p/:pid/edits/:eid/creating?job=`): follows the generation, then
 * the version's preview, starting it when there is none (ADR 0087). */
export function CreatingScreen() {
  const [params] = useSearchParams();
  return <Creating key={params.get("job") ?? ""} />; // a retry is a new job: start afresh
}

function Creating() {
  const { pid = "", eid = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const jobId = Number(params.get("job"));

  const edits = useQuery({
    queryKey: ["edits", pid],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/edits", { params: { path: { pid }, query: { limit: 200 } } })).data as unknown as { items: EditCardData[] }).items,
  });
  const card = edits.data?.find((e) => e.edit_id === eid);

  const generation = useQuery({
    queryKey: ["job", jobId],
    enabled: jobId > 0,
    refetchInterval: (q) => (q.state.data?.state === "running" || q.state.data?.state === "paused" ? POLL_MS : false),
    queryFn: async () => (await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } })).data as unknown as CreatingJob,
  });
  const made = generation.data?.state === "done";

  // Once the edit is made, its preview: the version's own if it has one (a reload, a
  // reused plan), else one started here, once (S17's rule, ADR 0049).
  const startFailed = useRef(false);
  const edit = useQuery({
    queryKey: ["edit", eid, "creating"],
    enabled: made,
    refetchInterval: (q) => {
      if (startFailed.current) return false;
      const row = q.state.data ? preview(q.state.data.renders) : undefined;
      return !row || ACTIVE.has(row.status) ? POLL_MS : false;
    },
    queryFn: async () => (await api.GET("/api/edits/{eid}", { params: { path: { eid } } })).data as unknown as { version: number; renders: RenderRow[] },
  });
  const row = edit.data ? preview(edit.data.renders) : undefined;
  const started = useRef(false);
  const start = useMutation({
    mutationFn: async (version: number) => {
      const { error } = await api.POST("/api/renders", { body: { edit_id: eid, version, final: false, codec: "h264" } });
      if (error) throw new Error("preview");
    },
    onError: () => {
      startFailed.current = true;
    },
    onSettled: () => void edit.refetch(),
  });
  const fresh = edit.isSuccess && !edit.isFetching;
  const startPreview = start.mutate;
  useEffect(() => {
    if (!fresh || row || started.current || !edit.data) return;
    started.current = true;
    startPreview(edit.data.version);
  }, [fresh, row, edit.data, startPreview]);
  const previewState: JobState | undefined = start.isError
    ? "failed"
    : row
      ? row.status === "done"
        ? "done"
        : row.status === "failed"
          ? "failed"
          : row.status === "paused"
            ? "paused"
            : "running"
      : made
        ? "running"
        : undefined;

  const cancel = useMutation({
    mutationFn: async () => {
      await api.POST("/api/jobs/{job_id}/{action}", { params: { path: { job_id: jobId, action: "cancel" } } });
    },
    onSuccess: () => void generation.refetch(),
  });
  const retry = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/edits/{eid}/generate", { params: { path: { eid } } });
      if (error || !data) throw new Error("generate");
      return (data as unknown as { job_id: number }).job_id;
    },
    onSuccess: (job) => setParams({ job: String(job) }, { replace: true }),
  });

  return (
    <CreatingView
      title={card ? cardName(card) : ""}
      seconds={card?.request.duration_s ?? 0}
      generation={generation.data}
      preview={previewState ? { state: previewState } : undefined}
      frame={(sid) => media.frame(pid, sid)}
      onBackground={() => navigate(`/p/${pid}/edits`)}
      onCancel={() => !cancel.isPending && cancel.mutate()}
      onRetry={() => !retry.isPending && retry.mutate()}
      onView={() => navigate(`/p/${pid}/edits/${eid}/storyboard`)}
    />
  );
}
