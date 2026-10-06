import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { CostCeilingDialog } from "@/features/shell/dialogs";
import { media } from "@/lib/media";
import { useToasts } from "@/lib/toasts";

import { AnalysisProgressView } from "./AnalysisProgressView";
import { FailuresDialog } from "./FailuresDialog";
import type { JobInfo, Progress } from "./model";

const POLL_MS = 2000; // S9: the live card updates at most every 2 s

/** S9 Analysis progress (`/p/:pid/analysis?job=`): polls the progress view and the job. */
export function AnalysisProgressScreen() {
  const { pid = "" } = useParams();
  const [search] = useSearchParams();
  const jobParam = search.get("job");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const [busy, setBusy] = useState(false);
  const [raise, setRaise] = useState(false);
  const [details, setDetails] = useState(false);

  const progress = useQuery({
    queryKey: ["analysis-progress", pid, jobParam],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/projects/{pid}/analysis/progress", {
        params: { path: { pid }, query: jobParam ? { job: Number(jobParam) } : {} },
      });
      if (error) throw new Error(response.status === 404 ? "none" : "failed");
      return data as unknown as Progress;
    },
    refetchInterval: (q) => (q.state.data && finished(qc, q.state.data.job_id) ? false : POLL_MS),
    retry: false,
  });
  const jobId = progress.data?.job_id;
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: jobId !== undefined,
    queryFn: async () => (await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId! } } })).data as unknown as JobInfo,
    refetchInterval: (q) => (q.state.data && ["done", "failed", "cancelled"].includes(q.state.data.state) ? false : POLL_MS),
  });

  const act = async (action: "pause" | "resume" | "cancel" | "retry-failed", body?: { cost_limit_usd: number }) => {
    if (jobId === undefined) return;
    setBusy(true);
    const { error } = await api.POST("/api/jobs/{job_id}/{action}", {
      params: { path: { job_id: jobId, action } },
      ...(body ? { body } : {}),
    });
    setBusy(false);
    if (error) toast({ kind: "error", message: "That didn't work. Try again." });
    void qc.invalidateQueries({ queryKey: ["job", jobId] });
    void qc.invalidateQueries({ queryKey: ["analysis-progress", pid] });
  };
  /** A cancelled run starts again as it was: the same preset, or the same deepening scope
   * and target. Finished work is reused (artifact keys). */
  const restart = async () => {
    const pr = progress.data;
    if (!pr) return;
    setBusy(true);
    const preset = ["quick", "balanced", "thorough"].includes(pr.mode ?? "") ? pr.mode! : "balanced";
    const d = pr.deepen;
    const body =
      pr.kind === "deepen" && d
        ? {
            mode: d.target ?? "thorough",
            scope: d.segment_ids.length
              ? { kind: "selection" as const, days: [], segment_ids: d.segment_ids }
              : d.days.length
                ? { kind: "days" as const, days: d.days, segment_ids: [] }
                : { kind: "trip" as const, days: [], segment_ids: [] },
          }
        : { mode: preset };
    // As it was: the limit the run had (perhaps raised here), not the project default.
    const limit = job.data?.cost_limit_usd;
    const { data, error } = await api.POST("/api/projects/{pid}/analysis-runs", {
      params: { path: { pid } },
      body: limit !== null && limit !== undefined ? { ...body, cost_limit: limit } : body,
    });
    setBusy(false);
    if (error || !data) toast({ kind: "error", message: "Couldn't resume the analysis. Try again." });
    else {
      const next = (data as { job_id: number | null }).job_id;
      if (next === null) toast({ kind: "info", message: "Nothing left to do: that part of the trip is already analyzed." });
      else navigate(`/p/${pid}/analysis?job=${next}`, { replace: true });
    }
  };

  if (progress.isError && progress.error.message !== "none") {
    return (
      <div className="flex flex-1 flex-col items-start gap-3 p-8">
        <h1 className="text-title text-text">Couldn't load the analysis</h1>
        <button type="button" className="text-small text-accent underline-offset-2 hover:underline" onClick={() => void progress.refetch()}>
          Try again
        </button>
      </div>
    );
  }
  if (progress.isError) {
    return (
      <div className="flex flex-1 flex-col items-start gap-3 p-8">
        <h1 className="text-title text-text">No analysis yet</h1>
        <p className="text-body text-text-muted">Choose how deep to look, then start the analysis.</p>
        <button type="button" className="text-small text-accent underline-offset-2 hover:underline" onClick={() => navigate(`/p/${pid}/analyze`)}>
          Set up the analysis
        </button>
      </div>
    );
  }
  if (!progress.data || !job.data) return <div aria-label="Loading" className="m-8 h-40 animate-pulse rounded-lg bg-surface-2" />;
  return (
    <>
      <AnalysisProgressView
        progress={progress.data}
        job={job.data}
        sheetUrl={(id) => media.mosaic(pid, id)}
        busy={busy}
        onPause={() => void act("pause")}
        onResume={() => void act("resume")}
        onCancel={() => void act("cancel")}
        onRaiseLimit={() => setRaise(true)}
        onRetry={() => void act("retry-failed")}
        onRestart={() => void restart()}
        onDetails={() => setDetails(true)}
        onOpenLibrary={() => navigate(`/p/${pid}/library`)}
        onCreateEdit={() => navigate(`/p/${pid}/edits/new`)}
      />
      {raise && (
        <CostCeilingDialog
          open
          limit={job.data.cost_limit_usd ?? job.data.cost_usd}
          spent={job.data.cost_usd}
          onKeepPaused={() => setRaise(false)}
          onRaise={(limit) => {
            setRaise(false);
            void act("resume", { cost_limit_usd: limit });
          }}
        />
      )}
      <FailuresDialog open={details} failures={progress.data.failures} onClose={() => setDetails(false)} />
    </>
  );
}

function finished(qc: ReturnType<typeof useQueryClient>, jobId: number): boolean {
  const j = qc.getQueryData<JobInfo>(["job", jobId]);
  return Boolean(j && ["done", "failed", "cancelled"].includes(j.state));
}
